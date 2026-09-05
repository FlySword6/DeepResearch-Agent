"""文本分块器：把长文档切成适合向量化的小块，并保留重叠上下文。"""

import hashlib
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TextChunker:
    """将文档切分为用于 embedding 的文本块。

    使用递归式字符切分策略：
      1. 先按段落边界（``\\n\\n``）切分
      2. 段落超过 *chunk_size* 时，再按句子边界切分
         （``.``、``!``、``?``）
      3. 句子仍过长时，按字符窗口切分并加入 overlap

    每个文本块都会返回 ``text``、``metadata`` 和 ``chunk_id`` 字段。
    """

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 64):
        """
        参数：
            chunk_size: 单个文本块的最大字符数。
            chunk_overlap: 相邻文本块之间的重叠字符数，用来保留上下文。
        """
        if chunk_overlap >= chunk_size:
            raise ValueError(
                f"chunk_overlap ({chunk_overlap}) must be less than "
                f"chunk_size ({chunk_size})"
            )
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    # ------------------------------------------------------------------
    # 对外 API
    # ------------------------------------------------------------------

    def chunk_text(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """把文本切成带重叠上下文的文本块。

        每个 chunk 字典包含：
          - ``text``：文本块内容
          - ``metadata``：调用方传入 metadata 的拷贝
          - ``chunk_id``：基于 SHA-256 的稳定文本块 ID

        参数：
            text: 需要切分的文档文本。
            metadata: 附加到每个 chunk 的元数据，例如来源、页码等。

        返回：
            chunk 字典列表。
        """
        if not text or not text.strip():
            return []

        metadata = metadata or {}
        chunks: List[Dict[str, Any]] = []

        # 第 1 层：先按段落切分，尽量保留自然语义边界。
        paragraphs = self._split_paragraphs(text)
        for para in paragraphs:
            if len(para) <= self.chunk_size:
                chunks.append(self._make_chunk(para, metadata))
            else:
                # 第 2 层：段落太长时，继续按句子切分。
                sentences = self._split_sentences(para)
                buffer = ""
                for sentence in sentences:
                    if len(buffer) + len(sentence) + 1 <= self.chunk_size:
                        buffer = (buffer + " " + sentence).strip()
                    else:
                        if buffer:
                            chunks.append(self._make_chunk(buffer, metadata))
                        # 第 3 层：单句仍太长时，只能按字符窗口切分。
                        if len(sentence) > self.chunk_size:
                            self._chunk_by_char(sentence, chunks, metadata)
                        else:
                            buffer = sentence
                if buffer:
                    chunks.append(self._make_chunk(buffer, metadata))

        # 应用 overlap：让相邻 chunk 带一点上下文，提升检索召回质量。
        if self.chunk_overlap > 0 and len(chunks) > 1:
            chunks = self._apply_overlap(chunks)

        logger.debug("Chunked text into %d chunks (size=%d, overlap=%d)",
                     len(chunks), self.chunk_size, self.chunk_overlap)
        return chunks

    def chunk_documents(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """一次性切分多个文档。

        每个文档至少需要包含 ``text`` 字段；可选 ``metadata`` 会合并到每个 chunk。

        参数：
            documents: 文档字典列表，每项包含 ``text``，可选 ``metadata``。

        返回：
            扁平化后的 chunk 字典列表。
        """
        all_chunks: List[Dict[str, Any]] = []
        for doc in documents:
            text = doc.get("text", "")
            meta = doc.get("metadata", {})
            chunks = self.chunk_text(text, metadata=meta)
            all_chunks.extend(chunks)
        return all_chunks

    # ------------------------------------------------------------------
    # 内部辅助函数
    # ------------------------------------------------------------------

    @staticmethod
    def _split_paragraphs(text: str) -> List[str]:
        """按双换行切分段落，并过滤空结果。"""
        raw = re.split(r"\n\s*\n", text)
        return [p.strip() for p in raw if p.strip()]

    @staticmethod
    def _split_sentences(text: str) -> List[str]:
        """把文本切分为句子。

        使用简单启发式：遇到 ``.``、``!``、``?`` 后接空白时切分。
        它不能覆盖所有边界情况，例如 "Mr. Smith"。
        """
        # 按句末标点后接空白或文本结尾进行切分。
        parts = re.split(r"(?<=[.!?])\s+", text)
        return [s.strip() for s in parts if s.strip()]

    @staticmethod
    def _make_chunk(text: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """构造单个 chunk 字典，并生成稳定的 ``chunk_id``。"""
        chunk_id = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        return {
            "text": text,
            "metadata": dict(metadata),
            "chunk_id": chunk_id,
        }

    def _chunk_by_char(
        self,
        text: str,
        chunks: List[Dict[str, Any]],
        metadata: Dict[str, Any],
    ) -> None:
        """按固定大小字符窗口切分文本，并加入 overlap。"""
        start = 0
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            chunk_text = text[start:end]
            if chunk_text.strip():
                chunks.append(self._make_chunk(chunk_text, metadata))
            start += self.chunk_size - self.chunk_overlap

    def _apply_overlap(self, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """为相邻 chunk 创建重叠窗口。

        实现方式是把上一个 chunk 的尾部拼到当前 chunk 前面，
        让边界附近的信息不会在检索时丢失。
        """
        overlapped: List[Dict[str, Any]] = []
        for i, chunk in enumerate(chunks):
            text = chunk["text"]
            meta = chunk["metadata"]

            # 第一个 chunk 没有前文，直接保留。
            if i == 0:
                overlapped.append(chunk)
                continue

            # 后续 chunk 前面拼接上一个 chunk 的尾部。
            prev_text = chunks[i - 1]["text"]
            overlap_text = prev_text[-self.chunk_overlap:] if len(prev_text) > self.chunk_overlap else prev_text
            new_text = (overlap_text + " " + text).strip()
            overlapped.append(self._make_chunk(new_text, meta))

        return overlapped
