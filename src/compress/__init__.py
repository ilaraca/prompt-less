"""Compressão RAG / docs (estágios doc_compress, rag_retrieve, rag_compress)."""
from src.compress.rag_compress import compress_rag, retrieve_chunks

__all__ = ["compress_rag", "retrieve_chunks"]
