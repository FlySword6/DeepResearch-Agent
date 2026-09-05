"""BM25 关键词索引：为 Hybrid RAG 提供精确词召回能力。

向量检索擅长语义相似，BM25 擅长实体名、数字、缩写和关键词精确匹配。
本模块把 child chunk 持久化为 JSON，并在进程启动时重建 BM25 索引。
"""

import json
import logging
import math
import os
import re
from collections import Counter
from typing import Any, Dict, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)


class BM25Store:
    """持久化 child chunk 并提供 BM25 检索。

    如果安装了 ``rank_bm25`` 会优先使用它；否则使用项目内置的轻量 BM25。
    两种实现对外返回格式一致，方便 RRF 融合层统一处理。
    """

    def __init__(self, persist_path: Optional[str] = None):
        index_dir = persist_path or settings.RAG_INDEX_PATH
        self._path = os.path.join(index_dir, "bm25_chunks.json")
        self._records: Dict[str, Dict[str, Any]] = {}
        self._tokens: Dict[str, List[str]] = {}
        self._rank_bm25 = None
        self._rank_ids: List[str] = []
        self._load()
        self._rebuild_index()

    async def add_documents(self, chunks: List[Dict[str, Any]]) -> List[str]:
        """写入 child chunk，并重建 BM25 索引。"""
        ids: List[str] = []
        for chunk in chunks:
            chunk_id = chunk.get("chunk_id")
            if not chunk_id:
                continue
            self._records[chunk_id] = {
                "chunk_id": chunk_id,
                "text": chunk.get("text", ""),
                "metadata": chunk.get("metadata", {}),
            }
            ids.append(chunk_id)
        self._persist()
        self._rebuild_index()
        return ids

    async def search(self, query: str, k: int = 10) -> List[Dict[str, Any]]:
        """按 BM25 分数检索 top-k child chunk。"""
        if not query.strip() or not self._records:
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        if self._rank_bm25 is not None:
            scores = self._rank_bm25.get_scores(query_tokens)
            ranked = sorted(
                zip(self._rank_ids, scores),
                key=lambda item: float(item[1]),
                reverse=True,
            )
        else:
            ranked = self._score_internal(query_tokens)

        results: List[Dict[str, Any]] = []
        for chunk_id, score in ranked[:k]:
            if score <= 0:
                continue
            record = self._records.get(chunk_id)
            if not record:
                continue
            results.append({
                "text": record["text"],
                "metadata": dict(record.get("metadata", {})),
                "score": float(score),
                "chunk_id": chunk_id,
            })
        return results

    async def delete_documents(self, ids: List[str]) -> None:
        """按 chunk_id 删除索引记录。"""
        changed = False
        for chunk_id in ids:
            if self._records.pop(chunk_id, None) is not None:
                changed = True
        if changed:
            self._persist()
            self._rebuild_index()

    async def delete_by_source(self, source: str) -> int:
        """删除指定来源文档对应的所有 child chunk。"""
        ids = [
            chunk_id
            for chunk_id, record in self._records.items()
            if record.get("metadata", {}).get("source") == source
        ]
        await self.delete_documents(ids)
        return len(ids)

    async def count(self) -> int:
        return len(self._records)

    async def list_documents(self) -> List[Dict[str, Any]]:
        """按来源聚合 child chunk 数量。"""
        sources: Counter = Counter()
        for record in self._records.values():
            source = record.get("metadata", {}).get("source", "unknown")
            sources[source] += 1
        return [{"source": source, "chunks": count} for source, count in sources.most_common()]

    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                for record in data:
                    chunk_id = record.get("chunk_id")
                    if chunk_id:
                        self._records[chunk_id] = record
        except Exception as exc:
            logger.warning("Failed to load BM25 index from %s: %s", self._path, exc)

    def _persist(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as fh:
            json.dump(list(self._records.values()), fh, ensure_ascii=False, indent=2)

    def _rebuild_index(self) -> None:
        self._tokens = {
            chunk_id: self._tokenize(record.get("text", ""))
            for chunk_id, record in self._records.items()
        }
        self._rank_bm25 = None
        self._rank_ids = list(self._tokens.keys())
        if not self._rank_ids:
            return

        try:
            from rank_bm25 import BM25Okapi  # type: ignore[import-untyped]

            corpus = [self._tokens[chunk_id] for chunk_id in self._rank_ids]
            self._rank_bm25 = BM25Okapi(corpus)
            logger.debug("BM25Store using rank_bm25 with %d chunks", len(corpus))
        except ImportError:
            logger.debug("rank_bm25 not installed, using internal BM25 scorer")

    def _score_internal(self, query_tokens: List[str]) -> List[tuple[str, float]]:
        docs = list(self._tokens.items())
        total_docs = len(docs)
        avgdl = sum(len(tokens) for _, tokens in docs) / max(total_docs, 1)
        df: Counter = Counter()
        for _, tokens in docs:
            df.update(set(tokens))

        k1 = 1.5
        b = 0.75
        query_counter = Counter(query_tokens)
        scored: List[tuple[str, float]] = []
        for chunk_id, tokens in docs:
            if not tokens:
                scored.append((chunk_id, 0.0))
                continue
            tf = Counter(tokens)
            doc_len = len(tokens)
            score = 0.0
            for token, query_weight in query_counter.items():
                freq = tf.get(token, 0)
                if freq <= 0:
                    continue
                idf = math.log(1 + (total_docs - df[token] + 0.5) / (df[token] + 0.5))
                denom = freq + k1 * (1 - b + b * doc_len / max(avgdl, 1e-9))
                score += query_weight * idf * (freq * (k1 + 1)) / denom
            scored.append((chunk_id, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """中英文混合分词；有 jieba 时优先使用。"""
        normalized = text.lower()
        try:
            import jieba  # type: ignore[import-untyped]

            return [token.strip() for token in jieba.lcut(normalized) if token.strip()]
        except ImportError:
            pass

        tokens = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", normalized)
        chinese_chars = [t for t in tokens if re.fullmatch(r"[\u4e00-\u9fff]", t)]
        bigrams = [
            chinese_chars[i] + chinese_chars[i + 1]
            for i in range(len(chinese_chars) - 1)
        ]
        return tokens + bigrams
