"""Embedder：为文本块生成向量表示。

配置了 ``OPENAI_API_KEY`` 时使用 OpenAI embedding。
否则回退到 scikit-learn 的 TF-IDF；如果 sklearn 也不可用，
则使用简单词频向量，保证本地开发仍可运行。
"""

import logging
import math
import os
from collections import Counter
from typing import List

import numpy as np

logger = logging.getLogger(__name__)


class Embedder:
    """为文本生成 embedding 向量。

    后端选择顺序如下，先可用者优先：
      1. 通过 DASHSCOPE_API_KEY 使用 DashScope
      2. 通过 OPENAI_API_KEY 使用 OpenAI embedding
      3. scikit-learn TfidfVectorizer，轻量词袋方案
      4. 简单词频/字符特征向量，无额外依赖
    """

    def __init__(self, model: str = "text-embedding-v3"):
        self.model = model
        self._openai_client = None
        self._sklearn_vectorizer = None
        self._vocab = []
        self._dimension = 0
        self._mode = self._resolve_backend()

    def _resolve_backend(self):
        # 1. DashScope：兼容 OpenAI SDK 的阿里云 embedding 接口。
        try:
            from app.config import settings
            api_key = settings.DASHSCOPE_API_KEY or os.environ.get("DASHSCOPE_API_KEY", "")
        except Exception:
            api_key = os.environ.get("DASHSCOPE_API_KEY", "")
        if api_key:
            try:
                from openai import AsyncOpenAI
                self._openai_client = AsyncOpenAI(api_key=api_key, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
                self.model = "text-embedding-v3"
                logger.info("Embedder: DashScope — %s", self.model)
                return "openai"
            except Exception as exc:
                logger.warning("DashScope init failed: %s", exc)

        # 2. OpenAI：使用默认 OpenAI embedding 接口。
        try:
            from app.config import settings
            api_key = settings.OPENAI_API_KEY or os.environ.get("OPENAI_API_KEY", "")
        except Exception:
            api_key = os.environ.get("OPENAI_API_KEY", "")
        if api_key:
            try:
                from openai import AsyncOpenAI
                self._openai_client = AsyncOpenAI(api_key=api_key)
                logger.info("Embedder: OpenAI — %s", self.model)
                return "openai"
            except Exception as exc:
                logger.warning("OpenAI init failed: %s", exc)

        # 3. sklearn TF-IDF：本地开发的轻量兜底方案。
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            self._sklearn_vectorizer = TfidfVectorizer(max_features=256, analyzer="char", ngram_range=(2, 4))
            if not api_key:
                logger.info("Embedder: sklearn TF-IDF (no API key configured)")
                return "sklearn"
        except ImportError:
            pass

        # 4. 简单词频兜底：没有外部服务和 sklearn 时仍可工作。
        logger.info("Embedder: simple word-count")
        return "simple"

    # ------------------------------------------------------------------
    # 对外 API
    # ------------------------------------------------------------------

    async def embed(self, text: str) -> List[float]:
        """为单条文本生成 embedding 向量。

        参数：
            text: 需要向量化的文本。

        返回：
            表示 embedding 向量的浮点数列表。
        """
        vectors = await self.embed_batch([text])
        return vectors[0]

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """批量生成多条文本的 embedding 向量。

        参数：
            texts: 需要向量化的文本列表。

        返回：
            与输入一一对应的向量列表。
        """
        if not texts:
            return []

        if self._mode == "openai":
            try:
                return await self._embed_openai(texts)
            except Exception as exc:
                logger.warning(
                    "External embedding unavailable, using local fallback: %s",
                    exc,
                )
                self._mode = "sklearn" if self._sklearn_vectorizer is not None else "simple"
                return await self.embed_batch(texts)
        elif self._mode == "sklearn":
            return self._embed_sklearn(texts)
        else:
            return self._embed_simple(texts)

    # ------------------------------------------------------------------
    # OpenAI 后端
    # ------------------------------------------------------------------

    async def _embed_openai(self, texts: List[str]) -> List[List[float]]:
        """通过 OpenAI 兼容 API 生成 embedding。"""
        client = self._openai_client
        assert client is not None  # 后端选择时已确认 client 可用。

        try:
            resp = await client.embeddings.create(
                model=self.model,
                input=texts,
            )
            vectors = [item.embedding for item in resp.data]
            logger.debug("OpenAI embedding returned %d vectors (dim=%d)",
                         len(vectors), len(vectors[0]) if vectors else 0)
            return vectors
        except Exception as exc:
            logger.error("OpenAI embedding failed: %s", exc)
            # OpenAI 调用失败时，如果可用则回退到 sklearn。
            if self._mode == "openai":
                self._mode = self._resolve_backend()
                if self._mode != "openai":
                    logger.warning("Falling back to %s backend after OpenAI error", self._mode)
                    return await self.embed_batch(texts)
            raise

    # ------------------------------------------------------------------
    # scikit-learn TF-IDF 后端
    # ------------------------------------------------------------------

    def _embed_sklearn(self, texts: List[str]) -> List[List[float]]:
        """通过 scikit-learn TF-IDF 生成向量。

        向量器会在第一次批量调用时惰性 fit，后续批次直接 transform。
        """
        vectorizer = self._sklearn_vectorizer
        assert vectorizer is not None

        # 第一次调用时拟合 TF-IDF 词表。
        if not hasattr(vectorizer, "vocabulary_") or not vectorizer.vocabulary_:
            logger.debug("Fitting TF-IDF vectorizer on first batch (%d texts)", len(texts))
            matrix = vectorizer.fit_transform(texts)
        else:
            matrix = vectorizer.transform(texts)

        # 稀疏矩阵转稠密向量，并归一化到单位长度。
        vectors: List[List[float]] = []
        for i in range(matrix.shape[0]):
            row = matrix[i].toarray().flatten().astype(np.float64)
            norm = np.linalg.norm(row)
            if norm > 0:
                row = row / norm
            vectors.append(row.tolist())

        return vectors

    # ------------------------------------------------------------------
    # 简单词频兜底后端
    # ------------------------------------------------------------------

    def _build_vocab(self, texts: List[str]) -> None:
        """使用最高频词构建词表。"""
        counter: Counter = Counter()
        for t in texts:
            tokens = self._tokenize(t)
            counter.update(tokens)
        # 保留 Top-N 词作为词表，控制向量维度。
        top = counter.most_common(256)
        self._vocab = [word for word, _ in top]
        self._dimension = len(self._vocab)
        logger.debug("Simple embedder vocab built: %d terms", self._dimension)

    def _embed_simple(self, texts: List[str]) -> List[List[float]]:
        """使用简单词频向量生成 embedding。"""
        if not self._vocab:
            self._build_vocab(texts)

        if self._dimension == 0:
            # 完全没有词表时返回零向量。
            return [[0.0] * 8 for _ in texts]

        vectors: List[List[float]] = []
        for text in texts:
            tokens = self._tokenize(text)
            counter = Counter(tokens)
            vec = [0.0] * self._dimension
            for i, word in enumerate(self._vocab):
                count = counter.get(word, 0)
                if count > 0:
                    # 简单的对数词频缩放，降低高频词支配程度。
                    vec[i] = 1.0 + math.log(count)
            # 归一化，方便使用余弦相似度。
            norm = math.sqrt(sum(v * v for v in vec))
            if norm > 0:
                vec = [v / norm for v in vec]
            vectors.append(vec)

        return vectors

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """小写化文本，并按非字母数字字符切分 token。"""
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
