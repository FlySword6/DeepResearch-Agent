"""Milvus 向量存储：为 RAG child chunk 提供生产级向量检索后端。"""

import asyncio
import json
import logging
from collections import Counter
from typing import Any, Dict, List, Optional

from app.config import settings
from app.rag.embedder import Embedder

logger = logging.getLogger(__name__)


class MilvusVectorStore:
    """使用 Milvus 存储和检索 child chunk embedding。

    该类刻意保持与 ``VectorStore`` 相同的对外接口，方便 RAGRetriever
    在 ChromaDB 和 Milvus 之间按配置切换。
    """

    def __init__(
        self,
        collection_name: Optional[str] = None,
        uri: Optional[str] = None,
        token: Optional[str] = None,
    ):
        self._collection_name = collection_name or settings.MILVUS_COLLECTION
        self._uri = uri or settings.MILVUS_URI
        self._token = token if token is not None else settings.MILVUS_TOKEN
        self._client = self._create_client()
        self._collection_ready = self._client.has_collection(self._collection_name)
        if self._collection_ready:
            self._load_collection()

    # ------------------------------------------------------------------
    # 对外 API
    # ------------------------------------------------------------------

    async def add_documents(
        self,
        chunks: List[Dict[str, Any]],
        embedder: Optional[Embedder] = None,
    ) -> List[str]:
        """批量写入 child chunk 和 embedding。"""
        if not chunks:
            return []
        if embedder is None:
            embedder = Embedder()

        texts = [c["text"] for c in chunks]
        embeddings = await embedder.embed_batch(texts)
        if not embeddings:
            return []

        await asyncio.to_thread(self._ensure_collection, len(embeddings[0]))

        records = [
            self._make_record(chunk, embedding)
            for chunk, embedding in zip(chunks, embeddings)
        ]
        ids = [record["chunk_id"] for record in records]
        await asyncio.to_thread(self._upsert_records, records)
        logger.debug("Upserted %d chunks into Milvus collection '%s'", len(ids), self._collection_name)
        return ids

    async def similarity_search(
        self,
        query: str,
        k: int = 5,
        embedder: Optional[Embedder] = None,
    ) -> List[Dict[str, Any]]:
        """使用 Milvus 执行向量相似度检索。"""
        if embedder is None:
            embedder = Embedder()
        query_vector = await embedder.embed(query)
        if not query_vector:
            return []

        await asyncio.to_thread(self._ensure_collection, len(query_vector))
        return await asyncio.to_thread(self._search, query_vector, k)

    async def delete_documents(self, ids: List[str]) -> None:
        """按 chunk_id 删除 Milvus 中的记录。"""
        if not ids or not self._collection_ready:
            return
        await asyncio.to_thread(self._delete_ids, ids)

    async def delete_by_source(self, source: str) -> int:
        """删除指定来源对应的所有 child chunk。"""
        if not source or not self._collection_ready:
            return 0
        escaped = self._escape_filter_value(source)
        expr = f'source == "{escaped}"'
        total_deleted = 0
        previous_batch: List[str] = []
        while True:
            ids = await asyncio.to_thread(self._query_ids, expr, settings.MILVUS_QUERY_LIMIT)
            if not ids:
                break
            if ids == previous_batch:
                logger.warning("Milvus delete_by_source saw the same batch twice; stopping to avoid a loop")
                break
            await asyncio.to_thread(self._delete_ids, ids)
            total_deleted += len(ids)
            if len(ids) < settings.MILVUS_QUERY_LIMIT:
                break
            previous_batch = ids
        return total_deleted

    async def count(self) -> int:
        """返回 collection 中的实体数量。"""
        if not self._collection_ready:
            return 0
        return await asyncio.to_thread(self._count)

    async def list_documents(self) -> List[Dict[str, Any]]:
        """按来源聚合 child chunk 数量。"""
        if not self._collection_ready:
            return []

        rows = await asyncio.to_thread(
            self._query_rows,
            "",
            ["source"],
            settings.MILVUS_QUERY_LIMIT,
        )
        sources: Counter = Counter()
        for row in rows:
            source = row.get("source", "unknown") or "unknown"
            sources[str(source)] += 1
        return [{"source": source, "chunks": count} for source, count in sources.most_common()]

    # ------------------------------------------------------------------
    # Milvus 内部实现
    # ------------------------------------------------------------------

    def _create_client(self):
        """创建 PyMilvus 客户端。"""
        from pymilvus import MilvusClient

        kwargs: Dict[str, Any] = {"uri": self._uri}
        if self._token:
            kwargs["token"] = self._token
        client = MilvusClient(**kwargs)
        logger.info("MilvusVectorStore connected (uri=%s, collection=%s)", self._uri, self._collection_name)
        return client

    def _ensure_collection(self, dimension: int) -> None:
        """确保 collection 和向量索引已经创建。"""
        if self._collection_ready and self._client.has_collection(self._collection_name):
            return

        from pymilvus import DataType

        schema = self._client.create_schema(
            auto_id=False,
            enable_dynamic_field=False,
            description="DeepResearch-Agent RAG child chunks",
        )
        schema.add_field("chunk_id", DataType.VARCHAR, is_primary=True, max_length=128)
        schema.add_field("text", DataType.VARCHAR, max_length=settings.MILVUS_TEXT_MAX_LENGTH)
        schema.add_field("source", DataType.VARCHAR, max_length=1024)
        schema.add_field("doc_type", DataType.VARCHAR, max_length=64)
        schema.add_field("parent_id", DataType.VARCHAR, max_length=128)
        schema.add_field("parent_index", DataType.INT64)
        schema.add_field("child_index", DataType.INT64)
        schema.add_field("metadata_json", DataType.VARCHAR, max_length=settings.MILVUS_METADATA_MAX_LENGTH)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=dimension)

        index_params = self._client.prepare_index_params()
        index_params.add_index(
            field_name="embedding",
            index_type="AUTOINDEX",
            metric_type=settings.MILVUS_METRIC_TYPE,
        )
        index_params.add_index(
            field_name="source",
            index_type="AUTOINDEX",
            index_name="source_index",
        )

        self._client.create_collection(
            collection_name=self._collection_name,
            schema=schema,
            index_params=index_params,
            consistency_level=settings.MILVUS_CONSISTENCY_LEVEL,
        )
        self._client.load_collection(self._collection_name)
        self._collection_ready = True
        logger.info(
            "Created Milvus collection '%s' (dim=%d, metric=%s)",
            self._collection_name,
            dimension,
            settings.MILVUS_METRIC_TYPE,
        )

    def _load_collection(self) -> None:
        """加载已有 collection；不同 Milvus 形态下失败不阻断后续操作。"""
        try:
            self._client.load_collection(self._collection_name)
        except Exception as exc:
            logger.debug("Milvus collection load skipped: %s", exc)

    def _upsert_records(self, records: List[Dict[str, Any]]) -> None:
        """优先 upsert；旧客户端不支持时退回 delete + insert。"""
        try:
            self._client.upsert(collection_name=self._collection_name, data=records)
        except AttributeError:
            ids = [record["chunk_id"] for record in records]
            self._delete_ids(ids)
            self._client.insert(collection_name=self._collection_name, data=records)

    def _search(self, query_vector: List[float], k: int) -> List[Dict[str, Any]]:
        """执行 Milvus search 并整理成项目统一格式。"""
        results = self._client.search(
            collection_name=self._collection_name,
            data=[query_vector],
            anns_field="embedding",
            limit=k,
            output_fields=[
                "chunk_id",
                "text",
                "source",
                "doc_type",
                "parent_id",
                "parent_index",
                "child_index",
                "metadata_json",
            ],
            search_params={"metric_type": settings.MILVUS_METRIC_TYPE},
        )

        formatted: List[Dict[str, Any]] = []
        if not results:
            return formatted

        for hit in results[0]:
            entity = hit.get("entity", hit)
            metadata = self._load_metadata(entity.get("metadata_json", ""))
            metadata.update({
                "source": entity.get("source", metadata.get("source", "")),
                "doc_type": entity.get("doc_type", metadata.get("doc_type", "")),
                "parent_id": entity.get("parent_id", metadata.get("parent_id", "")),
                "parent_index": entity.get("parent_index", metadata.get("parent_index", 0)),
                "child_index": entity.get("child_index", metadata.get("child_index", 0)),
            })
            raw_score = float(hit.get("distance", hit.get("score", 0.0)))
            formatted.append({
                "text": entity.get("text", ""),
                "metadata": metadata,
                "score": self._normalize_score(raw_score),
                "chunk_id": entity.get("chunk_id") or hit.get("id"),
            })
        return formatted

    def _query_rows(self, expr: str, output_fields: List[str], limit: int) -> List[Dict[str, Any]]:
        kwargs: Dict[str, Any] = {
            "collection_name": self._collection_name,
            "output_fields": output_fields,
            "limit": limit,
        }
        if expr:
            kwargs["filter"] = expr
        return self._client.query(**kwargs)

    def _query_ids(self, expr: str, limit: int) -> List[str]:
        rows = self._query_rows(expr, ["chunk_id"], limit)
        return [str(row["chunk_id"]) for row in rows if row.get("chunk_id")]

    def _delete_ids(self, ids: List[str]) -> None:
        if ids:
            self._client.delete(collection_name=self._collection_name, ids=ids)

    def _count(self) -> int:
        try:
            stats = self._client.get_collection_stats(self._collection_name)
            return int(stats.get("row_count", 0))
        except Exception:
            rows = self._query_rows("", ["chunk_id"], settings.MILVUS_QUERY_LIMIT)
            return len(rows)

    def _make_record(self, chunk: Dict[str, Any], embedding: List[float]) -> Dict[str, Any]:
        metadata = dict(chunk.get("metadata", {}))
        return {
            "chunk_id": str(chunk["chunk_id"]),
            "text": self._truncate(str(chunk.get("text", "")), settings.MILVUS_TEXT_MAX_LENGTH),
            "source": self._truncate(str(metadata.get("source", "unknown")), 1024),
            "doc_type": self._truncate(str(metadata.get("doc_type", "text")), 64),
            "parent_id": self._truncate(str(metadata.get("parent_id", "")), 128),
            "parent_index": int(metadata.get("parent_index", 0) or 0),
            "child_index": int(metadata.get("child_index", 0) or 0),
            "metadata_json": self._truncate(
                json.dumps(metadata, ensure_ascii=False, default=str),
                settings.MILVUS_METADATA_MAX_LENGTH,
            ),
            "embedding": embedding,
        }

    @staticmethod
    def _load_metadata(raw: str) -> Dict[str, Any]:
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _normalize_score(distance: float) -> float:
        """把 Milvus 返回值整理成“越大越相关”的展示分数。"""
        metric = settings.MILVUS_METRIC_TYPE.upper()
        if metric == "L2":
            return 1.0 / (1.0 + max(distance, 0.0))
        return distance

    @staticmethod
    def _truncate(value: str, max_length: int) -> str:
        return value[:max_length] if len(value) > max_length else value

    @staticmethod
    def _escape_filter_value(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')
