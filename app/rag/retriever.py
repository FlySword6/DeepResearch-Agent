"""Hybrid RAG 检索器：BM25 + 向量检索 + RRF 融合 + 父子 chunk。

导入时把文档切成两层：
  - parent chunk：较大的上下文块，最终返回给 Writer 使用
  - child chunk：较小的检索块，同时写入向量库和 BM25 索引

向量检索默认优先使用 Milvus；本地未启动 Milvus 时可降级到 ChromaDB。
检索时分别执行向量检索和 BM25 检索，再用 RRF 融合排名，最后根据
child 命中的 parent_id 回查 parent chunk，兼顾“找得准”和“给得全”。
"""

import hashlib
import logging
from typing import Any, Dict, List, Optional

from app.config import settings
from app.rag.bm25_store import BM25Store
from app.rag.chunker import TextChunker
from app.rag.embedder import Embedder
from app.rag.milvus_store import MilvusVectorStore
from app.rag.parent_store import ParentDocStore
from app.rag.vector_store import VectorStore

logger = logging.getLogger(__name__)


class RAGRetriever:
    """组合父子分块、向量检索、BM25 检索和 RRF 融合的高级检索器。"""

    def __init__(
        self,
        chunker: Optional[TextChunker] = None,
        embedder: Optional[Embedder] = None,
        vector_store: Optional[Any] = None,
        bm25_store: Optional[BM25Store] = None,
        parent_store: Optional[ParentDocStore] = None,
        parent_chunker: Optional[TextChunker] = None,
    ):
        """
        参数：
            chunker: child chunk 分块器；传 None 时使用默认 Hybrid RAG 配置。
            embedder: embedding 生成器。
            vector_store: child chunk 向量库；传 None 时按 RAG_VECTOR_BACKEND 创建。
            bm25_store: child chunk BM25 关键词索引。
            parent_store: parent chunk 持久化存储。
            parent_chunker: parent chunk 分块器。
        """
        self.parent_chunker = parent_chunker or TextChunker(
            chunk_size=settings.RAG_PARENT_CHUNK_SIZE,
            chunk_overlap=settings.RAG_PARENT_CHUNK_OVERLAP,
        )
        self.chunker = chunker or TextChunker(
            chunk_size=settings.RAG_CHILD_CHUNK_SIZE,
            chunk_overlap=settings.RAG_CHILD_CHUNK_OVERLAP,
        )
        self.embedder = embedder or Embedder()
        self.vector_store = vector_store or self._create_vector_store()
        self.bm25_store = bm25_store or BM25Store()
        self.parent_store = parent_store or ParentDocStore()

    def _create_vector_store(self):
        """根据配置创建向量后端，默认优先 Milvus。"""
        backend = (settings.RAG_VECTOR_BACKEND or "milvus").strip().lower()
        if backend in ("milvus", "auto"):
            try:
                return MilvusVectorStore()
            except Exception as exc:
                if backend == "milvus":
                    logger.warning("Milvus backend unavailable, falling back to ChromaDB: %s", exc)
                else:
                    logger.info("Milvus backend unavailable in auto mode, using ChromaDB: %s", exc)
        elif backend != "chroma":
            logger.warning("Unknown RAG_VECTOR_BACKEND='%s', using ChromaDB", backend)

        return VectorStore()

    # ------------------------------------------------------------------
    # 文档导入
    # ------------------------------------------------------------------

    async def ingest_document(
        self,
        content: str,
        source: str,
        doc_type: str = "text",
    ) -> List[str]:
        """处理文档并把 child chunk 写入向量库和 BM25 索引。"""
        base_metadata = {"source": source, "doc_type": doc_type}
        parent_chunks = self.parent_chunker.chunk_text(content, metadata=base_metadata)
        if not parent_chunks:
            logger.warning("Document '%s' produced no parent chunks", source)
            return []

        parent_records: List[Dict[str, Any]] = []
        child_chunks: List[Dict[str, Any]] = []

        for parent_index, parent in enumerate(parent_chunks):
            parent_text = parent["text"]
            parent_id = self._stable_id(source, "parent", parent_index, parent_text)
            parent_metadata = {
                **base_metadata,
                "parent_id": parent_id,
                "parent_index": parent_index,
            }

            raw_children = self.chunker.chunk_text(parent_text, metadata=parent_metadata)
            child_ids: List[str] = []
            for child_index, child in enumerate(raw_children):
                child_text = child["text"]
                child_id = self._stable_id(source, parent_id, child_index, child_text)
                child["chunk_id"] = child_id
                child["metadata"] = {
                    **child.get("metadata", {}),
                    "source": source,
                    "doc_type": doc_type,
                    "parent_id": parent_id,
                    "parent_index": parent_index,
                    "child_index": child_index,
                }
                child_chunks.append(child)
                child_ids.append(child_id)

            parent_records.append({
                "parent_id": parent_id,
                "text": parent_text,
                "metadata": parent_metadata,
                "child_ids": child_ids,
            })

        await self.parent_store.add_documents(parent_records)
        vector_ids = await self.vector_store.add_documents(child_chunks, embedder=self.embedder)
        await self.bm25_store.add_documents(child_chunks)

        logger.info(
            "Ingested '%s': %d parent chunks, %d child chunks",
            source,
            len(parent_records),
            len(vector_ids),
        )
        return vector_ids

    # ------------------------------------------------------------------
    # 文档检索
    # ------------------------------------------------------------------

    async def retrieve(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        """检索与 query 最相关的 parent chunk。"""
        vector_k = max(k, settings.RAG_VECTOR_TOP_K)
        bm25_k = max(k, settings.RAG_BM25_TOP_K)

        try:
            vector_results = await self.vector_store.similarity_search(
                query,
                k=vector_k,
                embedder=self.embedder,
            )
        except Exception as exc:
            logger.warning(
                "Vector retrieval failed; continuing with BM25-only recall: %s",
                exc,
            )
            vector_results = []

        try:
            bm25_results = await self.bm25_store.search(query, k=bm25_k)
        except Exception as exc:
            logger.warning(
                "BM25 retrieval failed; continuing with vector-only recall: %s",
                exc,
            )
            bm25_results = []

        fused_children = self._rrf_fuse(
            vector_results=vector_results,
            bm25_results=bm25_results,
            rrf_k=settings.RAG_RRF_K,
        )
        parent_results = await self._materialize_parent_results(fused_children, k=k)
        logger.debug(
            "Hybrid RAG retrieved %d parent results for '%s' (vector=%d, bm25=%d)",
            len(parent_results),
            query,
            len(vector_results),
            len(bm25_results),
        )
        return parent_results

    async def retrieve_with_scores(self, query: str, k: int = 5, score_threshold: float = 0.0) -> List[Dict[str, Any]]:
        """检索相关 parent chunk，并按最低 RRF 分数阈值过滤。"""
        all_results = await self.retrieve(query, k=k)
        filtered = [r for r in all_results if r.get("score", 0.0) >= score_threshold]
        logger.debug("%d hybrid results after threshold %.4f", len(filtered), score_threshold)
        return filtered

    async def list_documents(self) -> List[Dict[str, Any]]:
        """列出知识库来源文档及 parent/child 统计。"""
        parents = {item["source"]: item for item in await self.parent_store.list_documents()}
        children = {item["source"]: item for item in await self.bm25_store.list_documents()}
        sources = sorted(set(parents) | set(children))
        return [
            {
                "source": source,
                "parents": parents.get(source, {}).get("parents", 0),
                "chunks": children.get(source, {}).get("chunks", 0),
            }
            for source in sources
        ]

    async def delete_by_source(self, source: str) -> int:
        """删除指定来源的 parent、BM25 child 和向量库 child。"""
        bm25_deleted = await self.bm25_store.delete_by_source(source)
        parent_deleted = await self.parent_store.delete_by_source(source)
        vector_deleted = await self.vector_store.delete_by_source(source)
        logger.info(
            "Deleted source '%s' from hybrid RAG (parents=%d, bm25_children=%d, vector_children=%d)",
            source,
            parent_deleted,
            bm25_deleted,
            vector_deleted,
        )
        return max(bm25_deleted, vector_deleted)

    def _rrf_fuse(
        self,
        vector_results: List[Dict[str, Any]],
        bm25_results: List[Dict[str, Any]],
        rrf_k: int = 60,
    ) -> List[Dict[str, Any]]:
        """使用 Reciprocal Rank Fusion 融合两路 child chunk 排名。"""
        fused: Dict[str, Dict[str, Any]] = {}

        def add_result(result: Dict[str, Any], rank: int, source: str) -> None:
            chunk_id = result.get("chunk_id")
            if not chunk_id:
                return
            item = fused.setdefault(
                chunk_id,
                {
                    "chunk_id": chunk_id,
                    "text": result.get("text", ""),
                    "metadata": dict(result.get("metadata", {})),
                    "rrf_score": 0.0,
                    "vector_score": None,
                    "bm25_score": None,
                    "vector_rank": None,
                    "bm25_rank": None,
                },
            )
            item["rrf_score"] += 1.0 / (rrf_k + rank)
            if source == "vector":
                item["vector_score"] = result.get("score")
                item["vector_rank"] = rank
            else:
                item["bm25_score"] = result.get("score")
                item["bm25_rank"] = rank

        for rank, result in enumerate(vector_results, start=1):
            add_result(result, rank, "vector")
        for rank, result in enumerate(bm25_results, start=1):
            add_result(result, rank, "bm25")

        results = list(fused.values())
        results.sort(key=lambda item: item["rrf_score"], reverse=True)
        return results

    async def _materialize_parent_results(
        self,
        fused_children: List[Dict[str, Any]],
        k: int,
    ) -> List[Dict[str, Any]]:
        """把融合后的 child 命中聚合成 parent chunk 结果。"""
        grouped: Dict[str, Dict[str, Any]] = {}
        ordered_parent_ids: List[str] = []
        for child in fused_children:
            metadata = child.get("metadata", {})
            parent_id = metadata.get("parent_id") or child.get("chunk_id")
            if parent_id not in grouped:
                grouped[parent_id] = {
                    "parent_id": parent_id,
                    "score": 0.0,
                    "rrf_score": 0.0,
                    "vector_score": None,
                    "bm25_score": None,
                    "matched_children": [],
                    "child_hits": [],
                    "fallback_child": child,
                }
                ordered_parent_ids.append(parent_id)

            group = grouped[parent_id]
            group["score"] += child["rrf_score"]
            group["rrf_score"] += child["rrf_score"]
            group["matched_children"].append(child.get("text", ""))
            group["child_hits"].append(child)
            if child.get("vector_score") is not None:
                group["vector_score"] = max(
                    group["vector_score"] or child["vector_score"],
                    child["vector_score"],
                )
            if child.get("bm25_score") is not None:
                group["bm25_score"] = max(
                    group["bm25_score"] or child["bm25_score"],
                    child["bm25_score"],
                )

        parent_records = await self.parent_store.get_many(ordered_parent_ids)
        parent_results: List[Dict[str, Any]] = []
        for parent_id, group in grouped.items():
            parent = parent_records.get(parent_id)
            if parent:
                text = parent.get("text", "")
                metadata = dict(parent.get("metadata", {}))
                child_ids = parent.get("child_ids", [])
            else:
                fallback_child = group["fallback_child"]
                text = fallback_child.get("text", "")
                metadata = dict(fallback_child.get("metadata", {}))
                child_ids = [fallback_child.get("chunk_id")]

            metadata.update({
                "parent_id": parent_id,
                "retrieval_mode": "hybrid_rrf_parent_child",
                "child_count": len(child_ids),
            })

            parent_results.append({
                "text": text,
                "metadata": metadata,
                "score": group["score"],
                "rrf_score": group["rrf_score"],
                "vector_score": group["vector_score"],
                "bm25_score": group["bm25_score"],
                "chunk_id": parent_id,
                "parent_id": parent_id,
                "matched_children": group["matched_children"][:3],
                "child_hits": group["child_hits"][:5],
            })

        parent_results.sort(key=lambda item: item["score"], reverse=True)
        return parent_results[:k]

    @staticmethod
    def _stable_id(*parts: Any) -> str:
        raw = "::".join(str(part) for part in parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
