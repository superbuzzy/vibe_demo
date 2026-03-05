"""RAG 检索与生成逻辑。"""

from __future__ import annotations

import logging
import re
from typing import Any

from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from .config import (
    BM25_TOP_K,
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    DEEPSEEK_TEMPERATURE,
    MAX_SNIPPET_LEN,
    RETRIEVAL_MODE,
    TOP_K,
)
from .prompts import SYSTEM_PROMPT
from .vectorstore import get_embeddings, get_vectorstore

logger = logging.getLogger(__name__)

_BM25_RETRIEVER: BM25Retriever | None = None
_BM25_DIRTY = True
_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+")


def mark_bm25_dirty() -> None:
    """标记 BM25 索引需要重建。"""
    global _BM25_DIRTY
    _BM25_DIRTY = True


def _build_context(docs: list[Any]) -> str:
    """将检索结果拼成给模型的上下文。"""
    blocks: list[str] = []
    for doc in docs:
        source = doc.metadata.get("file_name") or doc.metadata.get("source", "unknown")
        page = doc.metadata.get("page")
        if isinstance(page, int):
            page = page + 1
        page_label = f"第{page}页" if page is not None else ""
        blocks.append(f"来源: {source} {page_label}\n内容: {doc.page_content}")
    return "\n\n".join(blocks)


def _build_sources(docs: list[Any]) -> list[dict[str, Any]]:
    """整理引用来源信息。"""
    sources: list[dict[str, Any]] = []
    for doc in docs:
        source = doc.metadata.get("file_name") or doc.metadata.get("source", "unknown")
        page = doc.metadata.get("page")
        if isinstance(page, int):
            page = page + 1
        snippet = " ".join(doc.page_content.strip().split())
        sources.append(
            {
                "source": source,
                "page": page,
                "snippet": snippet[:MAX_SNIPPET_LEN],
            }
        )
    return sources


def _bm25_tokenize(text: str) -> list[str]:
    """对中文按字切分，对英文按词切分。"""
    return _TOKEN_RE.findall(text.lower())

def _load_all_documents(vectorstore, batch_size: int = 1000) -> list[Document]:
    docs: list[Document] = []
    offset = 0

    while True:
        payload = vectorstore.get(
            include=["documents", "metadatas"], 
            limit=batch_size,
            offset=offset,
        )

        texts = payload.get("documents") or []
        metas = payload.get("metadatas") or []
        ids = payload.get("ids") or []  

        if not texts:
            break

        for text, meta, _id in zip(texts, metas, ids):
            meta = meta or {}
            meta.setdefault("id", _id)
            docs.append(Document(page_content=text, metadata=meta))

        offset += len(texts)
        if len(texts) < batch_size:
            break

    return docs



def _get_bm25_retriever(vectorstore, k: int) -> BM25Retriever | None:
    """按需构建 BM25 索引并返回检索器。"""
    global _BM25_RETRIEVER, _BM25_DIRTY
    if _BM25_RETRIEVER is None or _BM25_DIRTY:
        try:
            documents = _load_all_documents(vectorstore)
            if not documents:
                _BM25_RETRIEVER = None
            else:
                _BM25_RETRIEVER = BM25Retriever.from_documents(
                    documents, preprocess_func=_bm25_tokenize
                )
        except ImportError as exc:
            logger.warning("BM25 不可用: %s", exc)
            _BM25_RETRIEVER = None
        _BM25_DIRTY = False
    if _BM25_RETRIEVER is not None:
        _BM25_RETRIEVER.k = k
    return _BM25_RETRIEVER


def _merge_docs(
    semantic_docs: list[Document], bm25_docs: list[Document], limit: int
) -> list[Document]:
    """交错合并语义与关键词检索结果，去重后截断。"""
    merged: list[Document] = []
    seen: set[str] = set()
    max_len = max(len(semantic_docs), len(bm25_docs))
    for idx in range(max_len):
        for docs in (semantic_docs, bm25_docs):
            if idx >= len(docs):
                continue
            doc = docs[idx]
            key = (
                f"{doc.metadata.get('source')}|"
                f"{doc.metadata.get('page')}|"
                f"{hash(doc.page_content)}"
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(doc)
            if len(merged) >= limit:
                return merged
    return merged


def _retrieve_documents(question: str, vectorstore, top_k: int | None) -> list[Document]:
    """根据配置选择检索策略。"""
    mode = (RETRIEVAL_MODE or "semantic").lower()
    semantic_k = top_k or TOP_K
    bm25_k = top_k or BM25_TOP_K
    
    if mode == "semantic":
        retriever = vectorstore.as_retriever(search_kwargs={"k": semantic_k})
        return retriever.invoke(question)

    if mode == "bm25":
        bm25 = _get_bm25_retriever(vectorstore, bm25_k)
        return bm25.invoke(question) if bm25 else []
    # hybrid
    semantic_retriever = vectorstore.as_retriever(search_kwargs={"k": semantic_k})
    semantic_docs = semantic_retriever.invoke(question)

    bm25 = _get_bm25_retriever(vectorstore, bm25_k)
    bm25_docs = bm25.invoke(question) if bm25 else []
    return _merge_docs(semantic_docs, bm25_docs, semantic_k)


def _select_llm() -> ChatOpenAI | None:
    """按优先级选择可用大模型。"""
    if not DEEPSEEK_API_KEY:
        return None
    return ChatOpenAI(
        model=DEEPSEEK_MODEL,
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL,
        temperature=DEEPSEEK_TEMPERATURE,
    )


def answer_question(
    question: str, top_k: int | None = None, vectorstore=None
) -> tuple[str, list[dict[str, Any]]]:
    """执行检索与生成，返回回答与引用信息。"""
    llm = _select_llm()
    if llm is None:
        return "未配置可用的大模型，请设置 DEEPSEEK_API_KEY。", []

    if vectorstore is None:
        embeddings = get_embeddings()
        vectorstore = get_vectorstore(embeddings)

    docs = _retrieve_documents(question, vectorstore, top_k)
    if not docs:
        return "资料中没有找到相关信息。", []

    context = _build_context(docs)
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            ("human", "问题: {question}\n\n参考资料:\n{context}"),
        ]
    )

    response = llm.invoke(prompt.format_messages(question=question, context=context))

    return response.content, _build_sources(docs)
