"""知识记忆：跨任务持久化研究成果。

生产环境可使用 ChromaDB 做向量相似度检索；开发模式下使用内存存储，
并通过简单关键词重叠评分（类似 TF-IDF）实现检索。
"""

import logging
import math
import time
import uuid
from collections import Counter
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 简单关键词匹配辅助函数，不依赖外部库
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> List[str]:
    """把文本切分成小写字母数字 token。"""
    tokens: List[str] = []
    current: List[str] = []
    for ch in text.lower():
        if ch.isalnum():
            current.append(ch)
        else:
            if current:
                tokens.append("".join(current))
                current = []
    if current:
        tokens.append("".join(current))
    return tokens


def _tfidf_score(query_tokens: Set[str], doc_tokens: Counter, total_docs: int, doc_freq: Counter) -> float:
    """计算 query token 与文档之间的简化 TF-IDF 相似度。

    这里故意保持简单，只需要在没有外部 ML/NLP 库时给历史报告做基本排序。
    """
    score = 0.0
    for qt in query_tokens:
        if qt not in doc_tokens:
            continue
        tf = doc_tokens[qt] / max(sum(doc_tokens.values()), 1)
        idf = math.log((total_docs + 1) / (doc_freq.get(qt, 0) + 1)) + 1
        score += tf * idf
    return score


# ---------------------------------------------------------------------------
# 报告数据类
# ---------------------------------------------------------------------------

class KnowledgeEntry:
    """单条已存储的研究报告。"""

    def __init__(self, report_id: str, task: str, report: str, tags: List[str], timestamp: float):
        self.report_id = report_id
        self.task = task
        self.report = report
        self.tags = tags
        self.timestamp = timestamp

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "task": self.task,
            "report": self.report,
            "tags": list(self.tags),
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeEntry":
        return cls(
            report_id=data["report_id"],
            task=data["task"],
            report=data["report"],
            tags=list(data.get("tags", [])),
            timestamp=data.get("timestamp", 0.0),
        )


# ---------------------------------------------------------------------------
# KnowledgeMemory 跨任务知识记忆
# ---------------------------------------------------------------------------

class KnowledgeMemory:
    """跨任务保存研究成果，支持后续会话复用。

    生产环境可接入 ChromaDB；开发模式使用内存列表和关键词相似度匹配。
    """

    def __init__(self, chroma_path: str = "./data/chroma_db"):
        self._chroma_path = chroma_path
        self._entries: List[KnowledgeEntry] = []
        self._use_chromadb = False

        # 探测 ChromaDB 是否可用；当前开发模式仍使用内存兜底。
        try:
            import chromadb  # noqa: F401

            self._use_chromadb = True
            logger.info("chromadb available — using in-memory fallback for development")
        except ImportError:
            logger.info("chromadb not installed — using pure keyword-based matching")

    # ------------------------------------------------------------------
    # 对外 API
    # ------------------------------------------------------------------

    async def save_report(
        self, task: str, report: str, tags: Optional[List[str]] = None
    ) -> str:
        """存储一份研究报告。

        参数：
            task: 原始研究任务或问题。
            report: 完整报告文本。
            tags: 可选标签或分类。

        返回：
            唯一 report_id 字符串。
        """
        report_id = str(uuid.uuid4())
        entry = KnowledgeEntry(
            report_id=report_id,
            task=task,
            report=report,
            tags=tags or [],
            timestamp=time.time(),
        )
        self._entries.append(entry)
        logger.info("Saved report '%s' for task: %s", report_id, task[:60])
        return report_id

    async def query_similar(self, query: str, k: int = 3) -> List[Dict[str, Any]]:
        """使用关键词评分查找与 query 相似的历史报告。

        生产环境可替换为 embedding 检索；开发模式使用简化 TF-IDF 重叠分数。

        参数：
            query: 搜索查询。
            k: 最多返回结果数。

        返回：
            按相关性降序排序的报告字典列表。
        """
        if not self._entries:
            return []

        query_tokens = set(_tokenize(query))

        # 统计所有报告中的文档频率，用于简化 IDF 计算。
        total_docs = len(self._entries)
        doc_freq: Counter = Counter()
        doc_token_counts: List[Counter] = []
        for entry in self._entries:
            text = f"{entry.task} {' '.join(entry.tags)} {entry.report[:2000]}"
            tokens = Counter(_tokenize(text))
            doc_token_counts.append(tokens)
            for t in tokens:
                doc_freq[t] += 1

        # 为每条报告计算相关性分数。
        scored: List[tuple] = []
        for idx, entry in enumerate(self._entries):
            score = _tfidf_score(query_tokens, doc_token_counts[idx], total_docs, doc_freq)
            if score > 0:
                scored.append((score, entry))

        # 按分数降序排序并取 top-k。
        scored.sort(key=lambda x: x[0], reverse=True)
        results = [entry.to_dict() for _, entry in scored[:k]]
        return results

    async def get_report(self, report_id: str) -> Optional[Dict[str, Any]]:
        """按 ID 获取指定报告。

        参数：
            report_id: save_report() 返回的唯一标识。

        返回：
            报告字典；不存在时返回 None。
        """
        for entry in self._entries:
            if entry.report_id == report_id:
                return entry.to_dict()
        return None

    async def list_reports(self, limit: int = 20) -> List[Dict[str, Any]]:
        """列出近期报告，最新的排在前面。

        参数：
            limit: 最多返回报告数量。

        返回：
            按时间戳降序排序的报告字典列表。
        """
        sorted_entries = sorted(
            self._entries, key=lambda e: e.timestamp, reverse=True
        )
        return [e.to_dict() for e in sorted_entries[:limit]]

    # ------------------------------------------------------------------
    # 内部辅助函数
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        """返回已存储报告数量，主要方便测试。"""
        return len(self._entries)
