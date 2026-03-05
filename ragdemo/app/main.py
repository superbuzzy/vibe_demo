"""FastAPI 服务入口与文件索引逻辑。"""

from __future__ import annotations

import json
import logging
import shutil
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .config import (
    ALLOWED_EXTENSIONS,
    APP_TITLE,
    CHROMA_DIR,
    UPLOAD_DIR,
    UPLOAD_INDEX_FILE,
    UPLOAD_WATCH_INTERVAL,
)
from .ingest import load_documents, split_documents
from .rag import answer_question, mark_bm25_dirty
from .schemas import HealthResponse, QueryRequest, QueryResponse, UploadResponse
from .vectorstore import get_embeddings, get_vectorstore

app = FastAPI(title=APP_TITLE)

# 前端分离部署时的跨域支持
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:6008",
        "http://127.0.0.1:6008",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger(__name__)

_embeddings = None
_vectorstore = None
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_INDEX_FILE = _STATIC_DIR / "index.html"
_INGEST_LOCK = threading.Lock()
_WATCHER_STARTED = False

if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


# 读取已处理文件索引，避免重复向量化
def _load_ingest_index() -> dict[str, dict[str, float | int | str]]:
    if not UPLOAD_INDEX_FILE.exists():
        return {}
    try:
        data = json.loads(UPLOAD_INDEX_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(data, dict):
        return data
    return {}


# 保存文件索引信息
def _save_ingest_index(index: dict[str, dict[str, float | int | str]]) -> None:
    UPLOAD_INDEX_FILE.write_text(
        json.dumps(index, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


# 生成文件签名
def _file_signature(path: Path) -> dict[str, float | int]:
    stat = path.stat()
    return {"mtime": stat.st_mtime, "size": stat.st_size}


# 批量向量化指定文件
def _ingest_paths(paths: list[Path]) -> tuple[int, int]:
    if not paths:
        return 0, 0

    with _INGEST_LOCK:
        index = _load_ingest_index()
        if index and (not CHROMA_DIR.exists() or not any(CHROMA_DIR.iterdir())):
            index = {}
        documents = []
        updated = False

        for path in paths:
            if not path.is_file():
                continue
            if path.name == UPLOAD_INDEX_FILE.name:
                continue
            if path.suffix.lower() not in ALLOWED_EXTENSIONS:
                continue

            signature = _file_signature(path)
            entry = index.get(path.name)
            if (
                entry
                and entry.get("status") != "failed"
                and entry.get("mtime") == signature["mtime"]
                and entry.get("size") == signature["size"]
            ):
                continue

            try:
                loaded = load_documents([path])
                if loaded:
                    documents.extend(loaded)
                index[path.name] = {
                    "mtime": signature["mtime"],
                    "size": signature["size"],
                    "status": "ok",
                }
            except Exception as exc:
                logger.warning("Failed to ingest %s: %s", path.name, exc)
                index[path.name] = {
                    "mtime": signature["mtime"],
                    "size": signature["size"],
                    "status": "failed",
                }
            updated = True

        if updated:
            _save_ingest_index(index)

        if not documents:
            return 0, 0

        chunks = split_documents(documents)
        if chunks:
            vectorstore = _get_vectorstore()
            vectorstore.add_documents(chunks)
            if hasattr(vectorstore, "persist"):
                vectorstore.persist()
            # 文档变更后标记 BM25 索引需要重建
            mark_bm25_dirty()
        return len(documents), len(chunks)


# 启动上传目录热更新线程
def _start_upload_watcher() -> None:
    global _WATCHER_STARTED
    if _WATCHER_STARTED:
        return
    _WATCHER_STARTED = True

    def _watch() -> None:
        while True:
            try:
                if UPLOAD_DIR.exists():
                    _ingest_paths(list(UPLOAD_DIR.iterdir()))
            except Exception as exc:
                logger.warning("Upload watcher error: %s", exc)
            time.sleep(UPLOAD_WATCH_INTERVAL)

    threading.Thread(target=_watch, name="upload-watcher", daemon=True).start()


# 向量库单例
def _get_vectorstore():
    global _embeddings, _vectorstore
    if _vectorstore is None:
        _embeddings = _embeddings or get_embeddings()
        _vectorstore = get_vectorstore(_embeddings)
    return _vectorstore


@app.on_event("startup")
def _ensure_dirs() -> None:
    """确保目录存在并进行初次索引。"""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    _ingest_paths(list(UPLOAD_DIR.iterdir()))
    _start_upload_watcher()


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """健康检查。"""
    return HealthResponse(status="ok")


@app.get("/", include_in_schema=False)
def index() -> Response:
    """返回前端页面。"""
    if _INDEX_FILE.exists():
        return FileResponse(_INDEX_FILE)
    return HTMLResponse("<h2>UI not found</h2>", status_code=404)


# 保存上传文件到磁盘
def _save_upload(file: UploadFile) -> Path:
    filename = Path(file.filename or "").name
    if not filename:
        raise HTTPException(status_code=400, detail="Empty filename")

    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = UPLOAD_DIR / f"{uuid.uuid4().hex}_{filename}"
    with target.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return target


@app.post("/upload", response_model=UploadResponse)
async def upload_files(files: list[UploadFile] = File(...)) -> UploadResponse:
    """上传文件并触发向量化。"""
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    saved_paths: list[Path] = []
    skipped: list[str] = []

    for upload in files:
        try:
            saved_paths.append(_save_upload(upload))
        except HTTPException as exc:
            skipped.append(upload.filename or "unknown")
            if exc.status_code >= 500:
                raise
        finally:
            await upload.close()

    if not saved_paths:
        raise HTTPException(status_code=400, detail="No supported files uploaded")

    docs_loaded, chunks_indexed = _ingest_paths(saved_paths)

    return UploadResponse(
        files=[path.name for path in saved_paths],
        docs_loaded=docs_loaded,
        chunks_indexed=chunks_indexed,
        skipped=skipped,
    )


@app.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest) -> QueryResponse:
    """问答入口。"""
    try:
        answer, sources = answer_question(
            request.question, request.top_k, vectorstore=_get_vectorstore()
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return QueryResponse(answer=answer, sources=sources)
