from __future__ import annotations

from pathlib import Path
from typing import Iterable
import shutil
import subprocess
import tempfile

from langchain_core.documents import Document
from langchain_community.document_loaders import Docx2txtLoader, PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .config import ALLOWED_EXTENSIONS, CHUNK_OVERLAP, CHUNK_SIZE


class _TextLoader:
    """兜底：用纯文本构造一个 loader（接口兼容 loader.load()）"""
    def __init__(self, text: str, source_name: str):
        self._text = text
        self._source_name = source_name

    def load(self) -> list[Document]:
        return [Document(page_content=self._text, metadata={"source": self._source_name})]


def _convert_doc_to_docx(doc_path: Path) -> Path:
    """
    用 LibreOffice headless 把 .doc 转成 .docx，并做缓存避免重复转换。
    """
    cache_dir = doc_path.parent / ".rag_cache" / "docx"
    cache_dir.mkdir(parents=True, exist_ok=True)

    st = doc_path.stat()
    cache_docx = cache_dir / f"{doc_path.stem}_{st.st_mtime_ns}_{st.st_size}.docx"
    if cache_docx.exists():
        return cache_docx

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RuntimeError(
            "Need LibreOffice to convert .doc -> .docx. Install it: sudo apt-get install -y libreoffice"
        )

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        subprocess.run(
            [
                soffice,
                "--headless",
                "--nologo",
                "--nofirststartwizard",
                "--convert-to",
                "docx",
                "--outdir",
                str(td_path),
                str(doc_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        produced = td_path / f"{doc_path.stem}.docx"
        if not produced.exists():
            # 有时输出名可能略有差异，兜底找第一个 docx
            matches = list(td_path.glob("*.docx"))
            if not matches:
                raise RuntimeError("LibreOffice conversion finished but .docx not found.")
            produced = matches[0]

        produced.replace(cache_docx)

    return cache_docx


def _extract_doc_text_with_antiword(doc_path: Path) -> str:
    antiword = shutil.which("antiword")
    if not antiword:
        raise RuntimeError(
            "No LibreOffice and no antiword. Install one of them:\n"
            "  sudo apt-get install -y libreoffice\n"
            "or\n"
            "  sudo apt-get install -y antiword"
        )
    res = subprocess.run(
        [antiword, str(doc_path)],
        check=True,
        text=True,
        capture_output=True,
    )
    return res.stdout


def _get_loader(path: Path):
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return PyPDFLoader(str(path))

    if suffix == ".docx":
        return Docx2txtLoader(str(path))

    if suffix == ".doc":
        # 1) 优先用 LibreOffice 转 docx，再用 Docx2txtLoader
        try:
            docx_path = _convert_doc_to_docx(path)
            return Docx2txtLoader(str(docx_path))
        except Exception:
            # 2) 兜底：antiword 抽纯文本（格式会丢失，但可用于 RAG）
            text = _extract_doc_text_with_antiword(path)
            return _TextLoader(text=text, source_name=path.name)

    raise ValueError(f"Unsupported file type: {suffix}")


def load_documents(paths: Iterable[Path]) -> list[Document]:
    documents: list[Document] = []
    for path in paths:
        if path.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue

        loader = _get_loader(path)
        loaded = loader.load()

        for doc in loaded:
            # 关键：强制覆盖 source，避免 .doc 转换后 source 变成缓存 docx 路径
            doc.metadata["source"] = path.name
            doc.metadata["file_name"] = path.name
            doc.metadata["file_path"] = str(path)
            if path.suffix.lower() == ".doc":
                doc.metadata["legacy_doc"] = True

        documents.extend(loaded)

    return documents


def split_documents(documents: list[Document]) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=[
            "\n\n",
            "\n",
            "\u3002",
            "\uff01",
            "\uff1f",
            "\uff1b",
            "\uff0c",
            " ",
            "",
        ],
    )
    return splitter.split_documents(documents)


