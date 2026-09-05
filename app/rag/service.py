"""RAG 单例服务：让 API 和 Agent Tool 共享同一个检索器实例。"""

import logging
from typing import Optional

from app.rag.retriever import RAGRetriever

logger = logging.getLogger(__name__)

_rag_retriever: Optional[RAGRetriever] = None


def get_rag_retriever() -> RAGRetriever:
    """惰性创建全局 RAGRetriever。"""
    global _rag_retriever
    if _rag_retriever is None:
        _rag_retriever = RAGRetriever()
        logger.info("Created shared RAGRetriever")
    return _rag_retriever
