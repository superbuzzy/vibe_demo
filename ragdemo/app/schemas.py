from __future__ import annotations

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=20)


class SourceDocument(BaseModel):
    source: str
    page: int | None = None
    snippet: str


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceDocument]


class UploadResponse(BaseModel):
    files: list[str]
    docs_loaded: int
    chunks_indexed: int
    skipped: list[str]


class HealthResponse(BaseModel):
    status: str
