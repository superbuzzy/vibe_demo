"""Vector store and embedding setup."""

from __future__ import annotations

import os
import logging
from langchain_chroma import Chroma
from functools import lru_cache
from langchain_huggingface import HuggingFaceEmbeddings

from .config import (
    CHROMA_COLLECTION,
    CHROMA_DIR,
    EMBEDDING_DEVICE,
    EMBEDDING_MODEL_NAME,
    HF_ENDPOINT,
)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def get_embeddings() -> HuggingFaceEmbeddings:
    """Load HuggingFace embeddings."""
    os.environ.setdefault("HF_ENDPOINT", HF_ENDPOINT)
    return HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL_NAME,
        model_kwargs={"device": EMBEDDING_DEVICE},
    )


def get_vectorstore(embeddings: HuggingFaceEmbeddings | None = None) -> Chroma:
    """Return a persistent Chroma vector store instance."""
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    return Chroma(
        collection_name=CHROMA_COLLECTION,
        persist_directory=str(CHROMA_DIR),
        embedding_function=embeddings or get_embeddings(),
    )
