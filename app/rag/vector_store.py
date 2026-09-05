"""向量存储：持久化并查询文档 embedding。

优先使用 ChromaDB；不可用时回退到基于余弦相似度的内存向量库。
内存方案不会跨进程持久化，但足够支撑开发和测试。
"""

import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.rag.embedder import Embedder
from app.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 内存向量库条目
# ---------------------------------------------------------------------------

class _StoreEntry:
    """内存向量索引中的单个文档块。"""

    __slots__ = ("chunk_id", "text", "metadata", "embedding", "created_at")

    def __init__(
        self,
        chunk_id: str,
        text: str,
        metadata: Dict[str, Any],
        embedding: List[float],
    ):
        self.chunk_id = chunk_id
        self.text = text
        self.metadata = metadata
        self.embedding = embedding
        self.created_at = time.time()


# ---------------------------------------------------------------------------
# VectorStore 向量存储
# ---------------------------------------------------------------------------

class VectorStore:
    """用于存储和查询文档块 embedding 的向量数据库封装。

    安装了 ``chromadb`` 时委托给 ChromaDB，否则使用暴力余弦相似度的内存存储。

    参数：
        collection_name: ChromaDB collection 名称；内存兜底时忽略。
        persist_dir: ChromaDB 持久化目录；内存兜底时忽略。
    """

    def __init__(
        self,
        collection_name: str = "research_knowledge",
        persist_dir: Optional[str] = None,
    ):
        self._collection_name = collection_name
        self._persist_dir = persist_dir or settings.CHROMA_DB_PATH

        # 内存兜底状态。
        self._entries: Dict[str, _StoreEntry] = {}
        self._use_chromadb = False

        # 优先尝试初始化 ChromaDB。
        self._chroma_collection = None
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings

            client = chromadb.PersistentClient(
                path=self._persist_dir,
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            self._chroma_collection = client.get_or_create_collection(
                name=self._collection_name,
            )
            self._use_chromadb = True
            logger.info(
                "VectorStore using ChromaDB (collection='%s', persist=%s)",
                collection_name, self._persist_dir,
            )
        except ImportError:
            logger.info(
                "chromadb not installed — using in-memory vector store "
                "(data will be lost on restart)"
            )
        except Exception as exc:
            logger.warning(
                "ChromaDB initialisation failed — falling back to in-memory: %s", exc
            )

    # ------------------------------------------------------------------
    # 对外 API
    # ------------------------------------------------------------------

    async def add_documents(
        self,
        chunks: List[Dict[str, Any]],
        embedder: Optional[Embedder] = None,
    ) -> List[str]:
        if not chunks:
            return []
        if embedder is None:
            embedder = Embedder()
        texts = [c["text"] for c in chunks]
        embeddings = await embedder.embed_batch(texts)
        if self._use_chromadb and self._chroma_collection is not None:
            return self._add_chromadb(chunks, embeddings)
        else:
            return self._add_inmemory(chunks, embeddings)

    async def similarity_search(
        self,
        query: str,
        k: int = 5,
        embedder: Optional[Embedder] = None,
    ) -> List[Dict[str, Any]]:
        if embedder is None:
            embedder = Embedder()
        query_vector = await embedder.embed(query)
        if self._use_chromadb and self._chroma_collection is not None:
            return self._search_chromadb(query_vector, k)
        else:
            return self._search_inmemory(query_vector, k)

    async def delete_documents(self, ids: List[str]) -> None:
        if self._use_chromadb and self._chroma_collection is not None:
            try:
                self._chroma_collection.delete(ids=ids)
                logger.debug("Deleted %d documents from ChromaDB", len(ids))
            except Exception as exc:
                logger.error("Failed to delete from ChromaDB: %s", exc)
        else:
            for chunk_id in ids:
                self._entries.pop(chunk_id, None)
            logger.debug("Deleted %d documents from in-memory store", len(ids))

    async def count(self) -> int:
        if self._use_chromadb and self._chroma_collection is not None:
            return self._chroma_collection.count()
        return len(self._entries)

    async def list_documents(self) -> List[Dict[str, Any]]:
        """列出所有唯一来源文档及其 chunk 数量。"""
        from collections import Counter
        sources = Counter()
        if self._use_chromadb and self._chroma_collection is not None:
            try:
                all_data = self._chroma_collection.get()
                if all_data and all_data.get("metadatas"):
                    for m in all_data["metadatas"]:
                        src = m.get("source", "unknown") if m else "unknown"
                        if src:
                            sources[src] += 1
            except Exception as exc:
                logger.warning("list_documents chromadb error: %s", exc)
        else:
            for entry in self._entries.values():
                src = entry.metadata.get("source", "unknown")
                if src:
                    sources[src] += 1
        return [{"source": s, "chunks": c} for s, c in sources.most_common()]

    async def delete_by_source(self, source: str) -> int:
        """删除指定来源名称对应的所有 chunk。"""
        ids_to_delete = []
        if self._use_chromadb and self._chroma_collection is not None:
            try:
                results = self._chroma_collection.get(where={"source": source})
                if results and results.get("ids"):
                    ids_to_delete = results["ids"]
                    self._chroma_collection.delete(ids=ids_to_delete)
            except Exception as exc:
                logger.error("Failed to delete by source from ChromaDB: %s", exc)
        else:
            for cid, entry in list(self._entries.items()):
                if entry.metadata.get("source") == source:
                    ids_to_delete.append(cid)
                    self._entries.pop(cid, None)
        return len(ids_to_delete)

    # ------------------------------------------------------------------
    # ChromaDB 内部实现
    # ------------------------------------------------------------------

    def _add_chromadb(
        self,
        chunks: List[Dict[str, Any]],
        embeddings: List[List[float]],
    ) -> List[str]:
        """把 chunk 写入 ChromaDB。"""
        collection = self._chroma_collection
        assert collection is not None

        ids = [c["chunk_id"] for c in chunks]
        texts = [c["text"] for c in chunks]
        metadatas = [c.get("metadata", {}) for c in chunks]

        # ChromaDB 对 metadata 类型有限制，这里把复杂值转成字符串。
        safe_metadatas: List[Dict[str, str]] = []
        for m in metadatas:
            safe_metadatas.append(
                {k: str(v) if not isinstance(v, (str, int, float, bool)) else v
                 for k, v in m.items()}
            )

        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=safe_metadatas,
        )
        logger.debug("Added %d chunks to ChromaDB collection '%s'",
                     len(ids), self._collection_name)
        return ids

    def _search_chromadb(
        self, query_vector: List[float], k: int
    ) -> List[Dict[str, Any]]:
        """在 ChromaDB 中执行相似度搜索。"""
        collection = self._chroma_collection
        assert collection is not None

        results = collection.query(
            query_embeddings=[query_vector],
            n_results=k,
        )

        formatted: List[Dict[str, Any]] = []
        if not results["ids"]:
            return formatted

        for i in range(len(results["ids"][0])):
            formatted.append({
                "text": results["documents"][0][i] if results.get("documents") else "",
                "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
                "score": 1.0 - (results["distances"][0][i] if results.get("distances") else 0.0),
                "chunk_id": results["ids"][0][i],
            })

        return formatted

    # ------------------------------------------------------------------
    # 内存向量库内部实现
    # ------------------------------------------------------------------

    def _add_inmemory(
        self,
        chunks: List[Dict[str, Any]],
        embeddings: List[List[float]],
    ) -> List[str]:
        """把 chunk 写入内存向量库。"""
        ids: List[str] = []
        for chunk, emb in zip(chunks, embeddings):
            chunk_id = chunk.get("chunk_id") or str(uuid.uuid4())
            self._entries[chunk_id] = _StoreEntry(
                chunk_id=chunk_id,
                text=chunk["text"],
                metadata=chunk.get("metadata", {}),
                embedding=emb,
            )
            ids.append(chunk_id)
        logger.debug("Added %d chunks to in-memory store", len(ids))
        return ids

    def _search_inmemory(
        self, query_vector: List[float], k: int
    ) -> List[Dict[str, Any]]:
        """使用暴力余弦相似度搜索内存向量库。"""
        if not self._entries:
            return []

        query_np = np.array(query_vector, dtype=np.float64)
        query_norm = np.linalg.norm(query_np)
        if query_norm > 0:
            query_np = query_np / query_norm

        scored: List[Tuple[float, _StoreEntry]] = []
        for entry in self._entries.values():
            emb_np = np.array(entry.embedding, dtype=np.float64)
            emb_norm = np.linalg.norm(emb_np)
            if emb_norm > 0:
                emb_np = emb_np / emb_norm
            cos_sim = float(np.dot(query_np, emb_np))
            scored.append((cos_sim, entry))

        # 按相似度从高到低排序。
        scored.sort(key=lambda x: x[0], reverse=True)

        results: List[Dict[str, Any]] = []
        for score, entry in scored[:k]:
            results.append({
                "text": entry.text,
                "metadata": dict(entry.metadata),
                "score": score,
                "chunk_id": entry.chunk_id,
            })

        return results
