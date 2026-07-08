"""RAG Engine (Module 11) and Tool Executor registration."""

from __future__ import annotations

from app.rag.embeddings import BGE_M3_VECTOR_SIZE, BgeM3Embedder
from app.rag.filter_extraction import FilterExtractor
from app.rag.ingestion import IngestionService
from app.rag.qdrant_client import QdrantWrapper
from app.rag.repository import DocumentRepository, ProductRepository
from app.rag.retrieval_service import RetrievalService, retrieve_docs_tool, retrieve_products_tool
from app.rag.schemas import DocResult, ExtractedFilters, ProductResult
from app.tools.registry import tool_registry

tool_registry.register("retrieve_products", retrieve_products_tool, flag_name="enable_rag")
tool_registry.register("retrieve_docs", retrieve_docs_tool, flag_name="enable_rag")

__all__ = [
    "BGE_M3_VECTOR_SIZE",
    "BgeM3Embedder",
    "DocResult",
    "DocumentRepository",
    "ExtractedFilters",
    "FilterExtractor",
    "IngestionService",
    "ProductRepository",
    "ProductResult",
    "QdrantWrapper",
    "RetrievalService",
    "retrieve_docs_tool",
    "retrieve_products_tool",
]
