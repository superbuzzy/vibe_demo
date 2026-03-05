"""应用配置与路径设置。"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# 数据目录与持久化路径
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
CHROMA_DIR = DATA_DIR / "chroma"
UPLOAD_INDEX_FILE = UPLOAD_DIR / ".ingested.json"
# 上传目录扫描间隔（秒）
UPLOAD_WATCH_INTERVAL = int(os.getenv("UPLOAD_WATCH_INTERVAL", "5"))

APP_TITLE = os.getenv("APP_TITLE", "RAG Demo")

# DeepSeek 优先配置
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_TEMPERATURE = float(
    os.getenv("DEEPSEEK_TEMPERATURE", os.getenv("LLM_TEMPERATURE", "0.2"))
)


# 检索策略配置：semantic / bm25 / hybrid
RETRIEVAL_MODE = os.getenv("RETRIEVAL_MODE", "hybrid")
BM25_TOP_K = int(os.getenv("BM25_TOP_K", "4"))

HF_ENDPOINT = os.getenv("HF_ENDPOINT", "https://hf-mirror.com")
os.environ["HF_ENDPOINT"] = HF_ENDPOINT 

EMBEDDING_MODEL_NAME = os.getenv(
    "EMBEDDING_MODEL_NAME", "BAAI/bge-small-zh-v1.5"
)
EMBEDDING_DEVICE = os.getenv("EMBEDDING_DEVICE", "cpu")

CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "ragdemo")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "800"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "150"))
TOP_K = int(os.getenv("TOP_K", "4"))

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc"}

MAX_SNIPPET_LEN = int(os.getenv("MAX_SNIPPET_LEN", "240"))
