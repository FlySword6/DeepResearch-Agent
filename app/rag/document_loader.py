"""文档加载器：从 PDF、HTML、Markdown 和纯文本中读取内容。"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class DocumentLoader:
    """从多种来源加载文档。

    PDF 优先使用 PyMuPDF（``fitz``）提取，失败后退回到 ``textract``。
    HTML 使用 BeautifulSoup 解析；Markdown 和纯文本使用内置文件读取。
    """

    # ------------------------------------------------------------------
    # PDF 加载
    # ------------------------------------------------------------------

    async def load_pdf(self, path: str) -> str:
        """从 PDF 文件中提取文本。

        如果安装了 ``PyMuPDF``（``fitz``）则优先使用，否则回退到 ``textract``。

        参数：
            path: PDF 文件的本地路径。

        返回：
            提取出的文本内容。

        异常：
            FileNotFoundError: 路径不存在时抛出。
            ValueError: 无法提取任何文本时抛出。
        """
        self._ensure_file_exists(path)
        text = await self._try_fitz(path)
        if text:
            return text
        text = await self._try_textract(path)
        if text:
            return text
        raise ValueError(f"Could not extract any text from PDF: {path}")

    async def _try_fitz(self, path: str) -> Optional[str]:
        """尝试使用 PyMuPDF（fitz）提取 PDF 文本。"""
        try:
            import fitz  # type: ignore[import-untyped]
        except ImportError:
            logger.debug("PyMuPDF (fitz) not available — skipping fitz path")
            return None

        try:
            doc = fitz.open(path)
            pages = []
            for page_num in range(len(doc)):
                page = doc[page_num]
                text = page.get_text()
                if text.strip():
                    pages.append(text)
            doc.close()

            if pages:
                logger.info("Extracted %d pages from PDF via fitz: %s", len(pages), path)
                return "\n\n".join(pages)
            return None
        except Exception as exc:
            logger.warning("fitz extraction failed for %s: %s", path, exc)
            return None

    async def _try_textract(self, path: str) -> Optional[str]:
        """使用 textract 作为 PDF 文本提取兜底方案。"""
        try:
            import textract  # type: ignore[import-untyped]
        except ImportError:
            logger.debug("textract not available — skipping textract fallback")
            return None

        try:
            text = textract.process(path).decode("utf-8")
            if text.strip():
                logger.info("Extracted text from PDF via textract: %s", path)
                return text
            return None
        except Exception as exc:
            logger.warning("textract extraction failed for %s: %s", path, exc)
            return None

    # ------------------------------------------------------------------
    # HTML 加载
    # ------------------------------------------------------------------

    async def load_html(self, url_or_path: str) -> str:
        """从 HTML 来源中加载并提取可读文本。

        如果 *url_or_path* 以 ``http://`` 或 ``https://`` 开头，则通过 HTTP 拉取；
        否则按本地文件路径处理。

        参数：
            url_or_path: HTML 文档的 URL 或本地路径。

        返回：
            提取出的文本内容，会去除标签并规范化空白。

        异常：
            ValueError: 无法提取文本时抛出。
            FileNotFoundError: 本地路径不存在时抛出。
        """
        import httpx
        from bs4 import BeautifulSoup

        if url_or_path.startswith(("http://", "https://")):
            logger.info("Fetching HTML from URL: %s", url_or_path)
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url_or_path, follow_redirects=True)
                resp.raise_for_status()
                html = resp.text
        else:
            self._ensure_file_exists(url_or_path)
            with open(url_or_path, "r", encoding="utf-8", errors="replace") as fh:
                html = fh.read()

        soup = BeautifulSoup(html, "html.parser")

        # 移除脚本、样式、导航等噪声标签，减少无关文本进入知识库。
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        # 优先提取 article/main 正文区域，找不到时退回 body。
        container = soup.find("article") or soup.find("main") or soup.find("body")
        if container is None:
            container = soup

        text = container.get_text(separator="\n", strip=True)
        if not text:
            raise ValueError(f"No text content found in HTML: {url_or_path}")

        logger.info("Extracted %d characters from HTML: %s", len(text), url_or_path)
        return text

    # ------------------------------------------------------------------
    # Markdown / 纯文本加载
    # ------------------------------------------------------------------

    async def load_markdown(self, path: str) -> str:
        """按纯文本读取 Markdown 文件。

        参数：
            path: ``.md`` 文件的本地路径。

        返回：
            原始文件内容。

        异常：
            FileNotFoundError: 路径不存在时抛出。
        """
        self._ensure_file_exists(path)
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
        logger.info("Loaded %d characters from markdown: %s", len(content), path)
        return content

    async def load_text(self, path: str) -> str:
        """读取普通文本文件。

        参数：
            path: ``.txt`` 文件的本地路径。

        返回：
            原始文件内容。

        异常：
            FileNotFoundError: 路径不存在时抛出。
        """
        self._ensure_file_exists(path)
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
        logger.info("Loaded %d characters from text file: %s", len(content), path)
        return content

    # ------------------------------------------------------------------
    # 辅助函数
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_file_exists(path: str) -> None:
        """路径不存在时抛出 ``FileNotFoundError``。"""
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Document not found: {path}")
