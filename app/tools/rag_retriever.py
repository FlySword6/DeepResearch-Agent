"""RAGRetrieverTool — wraps RAGRetriever for use by agents via ToolRouter."""

import logging
from typing import Any, Dict, Optional

from app.rag.retriever import RAGRetriever
from app.rag.service import get_rag_retriever
from app.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# Module-level singleton so all tool calls share the same index
_rag_retriever: Optional[RAGRetriever] = None


def _get_rag_retriever() -> RAGRetriever:
    """Lazy-initialised singleton RAGRetriever."""
    return get_rag_retriever()


class RAGRetrieverTool(BaseTool):
    """Tool that retrieves relevant information from the research knowledge base.

    Supports two actions:

    - **retrieve**: Search the vector store for chunks similar to a query.
      Parameters: ``query`` (str), optional ``k`` (int, default 5).

    - **ingest**: Add a document to the vector store.
      Parameters: ``content`` (str), ``source`` (str), optional
      ``doc_type`` (str, default ``"text"``).
    """

    name: str = "rag_retrieve"
    description: str = (
        "Retrieve relevant information from the research knowledge base "
        "using RAG (Retrieval-Augmented Generation). Supports 'retrieve' "
        "for searching and 'ingest' for adding documents."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["retrieve", "ingest"],
                "description": "Action to perform: 'retrieve' to search, 'ingest' to add a document.",
            },
            "query": {
                "type": "string",
                "description": "Search query (required for action='retrieve').",
            },
            "k": {
                "type": "integer",
                "description": "Number of results to return (default 5).",
                "default": 5,
            },
            "content": {
                "type": "string",
                "description": "Document content (required for action='ingest').",
            },
            "source": {
                "type": "string",
                "description": "Source identifier for the document (required for action='ingest').",
            },
            "doc_type": {
                "type": "string",
                "description": "Document type label (default 'text').",
                "default": "text",
            },
        },
        "required": ["action"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the requested RAG action.

        Supported keyword arguments:
          - ``action`` (required): ``"retrieve"`` or ``"ingest"``
          - ``query`` (str): search query for retrieve
          - ``k`` (int): max results for retrieve (default 5)
          - ``content`` (str): document text for ingest
          - ``source`` (str): document source for ingest
          - ``doc_type`` (str): document type for ingest (default ``"text"``)

        Returns:
            :class:`ToolResult` with result data in ``.data``.
        """
        action = kwargs.get("action")
        if not action:
            return ToolResult(
                success=False,
                error="Missing required parameter: 'action' (must be 'retrieve' or 'ingest').",
            )

        retriever = _get_rag_retriever()

        if action == "retrieve":
            return await self._handle_retrieve(retriever, kwargs)
        elif action == "ingest":
            return await self._handle_ingest(retriever, kwargs)
        else:
            return ToolResult(
                success=False,
                error=f"Unknown action '{action}'. Supported: retrieve, ingest.",
            )

    async def _handle_retrieve(
        self, retriever: RAGRetriever, params: Dict[str, Any]
    ) -> ToolResult:
        """Handle a retrieve action."""
        query = params.get("query")
        if not query:
            return ToolResult(
                success=False,
                error="Missing required parameter 'query' for retrieve action.",
            )
        k = params.get("k", 5)
        try:
            results = await retriever.retrieve(query, k=k)
            return ToolResult(
                success=True,
                data={
                    "results": results,
                    "count": len(results),
                    "query": query,
                },
                metadata={"k": k, "action": "retrieve"},
            )
        except Exception as exc:
            logger.exception("RAG retrieve failed")
            return ToolResult(
                success=False,
                error=f"RAG retrieve failed: {exc}",
            )

    async def _handle_ingest(
        self, retriever: RAGRetriever, params: Dict[str, Any]
    ) -> ToolResult:
        """Handle an ingest action."""
        content = params.get("content")
        source = params.get("source")
        if not content or not source:
            return ToolResult(
                success=False,
                error="Missing required parameters 'content' and 'source' for ingest action.",
            )
        doc_type = params.get("doc_type", "text")
        try:
            chunk_ids = await retriever.ingest_document(
                content=content,
                source=source,
                doc_type=doc_type,
            )
            return ToolResult(
                success=True,
                data={
                    "chunk_ids": chunk_ids,
                    "count": len(chunk_ids),
                    "source": source,
                },
                metadata={"action": "ingest", "doc_type": doc_type},
            )
        except Exception as exc:
            logger.exception("RAG ingest failed")
            return ToolResult(
                success=False,
                error=f"RAG ingest failed: {exc}",
            )
