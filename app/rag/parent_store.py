"""父块存储：保存 RAG 父子 chunk 中的 parent chunk 原文。"""

import json
import logging
import os
from collections import Counter
from typing import Any, Dict, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)


class ParentDocStore:
    """持久化 parent chunk，供 child 命中后回查完整上下文。"""

    def __init__(self, persist_path: Optional[str] = None):
        index_dir = persist_path or settings.RAG_INDEX_PATH
        self._path = os.path.join(index_dir, "parent_chunks.json")
        self._records: Dict[str, Dict[str, Any]] = {}
        self._load()

    async def add_documents(self, parents: List[Dict[str, Any]]) -> List[str]:
        ids: List[str] = []
        for parent in parents:
            parent_id = parent.get("parent_id")
            if not parent_id:
                continue
            self._records[parent_id] = {
                "parent_id": parent_id,
                "text": parent.get("text", ""),
                "metadata": parent.get("metadata", {}),
                "child_ids": list(parent.get("child_ids", [])),
            }
            ids.append(parent_id)
        self._persist()
        return ids

    async def get_many(self, parent_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        return {
            parent_id: self._records[parent_id]
            for parent_id in parent_ids
            if parent_id in self._records
        }

    async def delete_by_source(self, source: str) -> int:
        ids = [
            parent_id
            for parent_id, record in self._records.items()
            if record.get("metadata", {}).get("source") == source
        ]
        for parent_id in ids:
            self._records.pop(parent_id, None)
        if ids:
            self._persist()
        return len(ids)

    async def list_documents(self) -> List[Dict[str, Any]]:
        sources: Counter = Counter()
        for record in self._records.values():
            source = record.get("metadata", {}).get("source", "unknown")
            sources[source] += 1
        return [{"source": source, "parents": count} for source, count in sources.most_common()]

    async def count(self) -> int:
        return len(self._records)

    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                for record in data:
                    parent_id = record.get("parent_id")
                    if parent_id:
                        self._records[parent_id] = record
        except Exception as exc:
            logger.warning("Failed to load parent chunks from %s: %s", self._path, exc)

    def _persist(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as fh:
            json.dump(list(self._records.values()), fh, ensure_ascii=False, indent=2)
