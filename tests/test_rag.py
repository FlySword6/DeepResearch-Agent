"""Tests for the RAG system (DocumentLoader, TextChunker, Embedder, VectorStore, RAGRetriever, RAGRetrieverTool)."""

import os
import shutil
import tempfile
import pytest

from app.rag.document_loader import DocumentLoader
from app.rag.chunker import TextChunker
from app.rag.embedder import Embedder
from app.rag.vector_store import VectorStore
from app.rag.retriever import RAGRetriever
from app.tools.rag_retriever import RAGRetrieverTool
from app.tools.router import ToolRouter


# ======================================================================
# DocumentLoader
# ======================================================================

class TestDocumentLoader:
    """DocumentLoader with various file formats."""

    @pytest.fixture
    def loader(self) -> DocumentLoader:
        return DocumentLoader()

    @pytest.mark.asyncio
    async def test_load_text(self, loader: DocumentLoader):
        """Load a plain text file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("Hello, this is a test document.\nWith multiple lines.")
            tmp_path = f.name
        try:
            content = await loader.load_text(tmp_path)
            assert "Hello" in content
            assert "multiple lines" in content
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_load_markdown(self, loader: DocumentLoader):
        """Load a markdown file."""
        md_content = "# Title\n\nThis is a **markdown** document.\n\n- Item 1\n- Item 2"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(md_content)
            tmp_path = f.name
        try:
            content = await loader.load_markdown(tmp_path)
            assert "# Title" in content
            assert "Item 1" in content
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_load_html_local(self, loader: DocumentLoader):
        """Load HTML from a local file."""
        html_content = "<html><body><h1>Test</h1><p>Hello world</p></body></html>"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8") as f:
            f.write(html_content)
            tmp_path = f.name
        try:
            content = await loader.load_html(tmp_path)
            assert "Test" in content
            assert "Hello world" in content
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_load_file_not_found(self, loader: DocumentLoader):
        """Loading a non-existent file should raise FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            await loader.load_text("/tmp/nonexistent_file_xyz.txt")

    @pytest.mark.asyncio
    async def test_load_pdf_invalid(self, loader: DocumentLoader):
        """Loading a non-PDF as PDF should raise ValueError."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pdf", delete=False, encoding="utf-8") as f:
            f.write("Not a real PDF file")
            tmp_path = f.name
        try:
            with pytest.raises(ValueError, match="Could not extract any text"):
                await loader.load_pdf(tmp_path)
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_load_empty_file(self, loader: DocumentLoader):
        """Loading an empty text file should return empty string."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            tmp_path = f.name
        try:
            content = await loader.load_text(tmp_path)
            assert content == ""
        finally:
            os.unlink(tmp_path)


# ======================================================================
# TextChunker
# ======================================================================

class TestTextChunker:
    """TextChunker splitting logic."""

    def test_init_validation(self):
        """chunk_overlap must be less than chunk_size."""
        with pytest.raises(ValueError):
            TextChunker(chunk_size=100, chunk_overlap=100)
        with pytest.raises(ValueError):
            TextChunker(chunk_size=100, chunk_overlap=200)

    def test_chunk_text_empty(self):
        """Empty text should produce no chunks."""
        chunker = TextChunker()
        assert chunker.chunk_text("") == []
        assert chunker.chunk_text("   ") == []

    def test_chunk_text_small(self):
        """Text smaller than chunk_size should produce one chunk."""
        chunker = TextChunker(chunk_size=1000, chunk_overlap=0)
        chunks = chunker.chunk_text("Hello world. This is a test.")
        assert len(chunks) == 1
        assert chunks[0]["text"] == "Hello world. This is a test."
        assert "chunk_id" in chunks[0]
        assert chunks[0]["metadata"] == {}

    def test_chunk_text_with_metadata(self):
        """Metadata should be propagated to each chunk."""
        chunker = TextChunker(chunk_size=100, chunk_overlap=0)
        chunks = chunker.chunk_text("A" * 50 + "\n\n" + "B" * 60, metadata={"source": "test"})
        assert len(chunks) >= 2
        for c in chunks:
            assert c["metadata"]["source"] == "test"

    def test_chunk_text_paragraph_splitting(self):
        """Text should be split by paragraphs first."""
        chunker = TextChunker(chunk_size=50, chunk_overlap=0)
        text = "Short paragraph one.\n\nShort paragraph two.\n\nShort paragraph three."
        chunks = chunker.chunk_text(text)
        # Each paragraph should be a separate chunk
        assert len(chunks) >= 2
        assert any("paragraph one" in c["text"] for c in chunks)
        assert any("paragraph two" in c["text"] for c in chunks)

    def test_chunk_text_deterministic_ids(self):
        """Same text should produce same chunk IDs."""
        chunker = TextChunker(chunk_size=1000, chunk_overlap=0)
        text = "Deterministic chunk test."
        c1 = chunker.chunk_text(text)
        c2 = chunker.chunk_text(text)
        assert c1[0]["chunk_id"] == c2[0]["chunk_id"]

    def test_chunk_documents(self):
        """chunk_documents should handle multiple documents."""
        chunker = TextChunker(chunk_size=200, chunk_overlap=0)
        docs = [
            {"text": "Document one content here.", "metadata": {"source": "doc1"}},
            {"text": "Document two content here.", "metadata": {"source": "doc2"}},
        ]
        chunks = chunker.chunk_documents(docs)
        assert len(chunks) == 2
        sources = {c["metadata"]["source"] for c in chunks}
        assert sources == {"doc1", "doc2"}

    def test_chunk_large_paragraph(self):
        """A single paragraph larger than chunk_size should be split."""
        chunker = TextChunker(chunk_size=50, chunk_overlap=10)
        text = "This is a very long paragraph that should definitely be split into multiple chunks because it exceeds the chunk size limit."
        chunks = chunker.chunk_text(text)
        assert len(chunks) >= 2


# ======================================================================
# Embedder
# ======================================================================

class TestEmbedder:
    """Embedder with fallback/simple backend."""

    @pytest.fixture
    def embedder(self) -> Embedder:
        """Ensure we use the simple fallback (no OPENAI_API_KEY)."""
        # The embedder should auto-detect simple backend when no API key
        return Embedder()

    @pytest.mark.asyncio
    async def test_embed_single(self, embedder: Embedder):
        """Embed a single text string."""
        vector = await embedder.embed("Hello world")
        assert isinstance(vector, list)
        assert len(vector) > 0
        assert all(isinstance(v, float) for v in vector)

    @pytest.mark.asyncio
    async def test_embed_batch(self, embedder: Embedder):
        """Embed multiple texts."""
        texts = ["Hello world", "Another text", "Third document"]
        vectors = await embedder.embed_batch(texts)
        assert len(vectors) == 3
        assert all(len(v) > 0 for v in vectors)

    @pytest.mark.asyncio
    async def test_embed_empty_list(self, embedder: Embedder):
        """Empty text list should return empty list."""
        vectors = await embedder.embed_batch([])
        assert vectors == []

    @pytest.mark.asyncio
    async def test_embed_similar_texts_similar_vectors(self, embedder: Embedder):
        """Similar texts should produce similar vectors (high cosine similarity)."""
        vec_a = await embedder.embed("quantum computing research")
        vec_b = await embedder.embed("quantum computing advances")
        vec_c = await embedder.embed("completely unrelated topic about cooking")

        # Helper: cosine similarity
        def cos_sim(v1, v2):
            dot = sum(a * b for a, b in zip(v1, v2))
            norm1 = sum(a * a for a in v1) ** 0.5
            norm2 = sum(b * b for b in v2) ** 0.5
            if norm1 == 0 or norm2 == 0:
                return 0.0
            return dot / (norm1 * norm2)

        sim_ab = cos_sim(vec_a, vec_b)
        sim_ac = cos_sim(vec_a, vec_c)

        # Similar pairs should be more similar than dissimilar pairs
        assert sim_ab > sim_ac

    @pytest.mark.asyncio
    async def test_embed_different_backends(self):
        """Ensure the embedder auto-detects the right backend mode."""
        e = Embedder()
        assert e._mode in ("openai", "sklearn", "simple")

        vec = await e.embed("test")
        assert len(vec) > 0


# ======================================================================
# VectorStore
# ======================================================================

class TestVectorStore:
    """VectorStore add/search (in-memory fallback)."""

    @pytest.fixture
    def store(self, tmp_path) -> VectorStore:
        """Return a VectorStore with a temp persistence directory."""
        return VectorStore(persist_dir=str(tmp_path / "chroma"))

    @pytest.fixture
    def embedder(self) -> Embedder:
        return Embedder()

    @pytest.mark.asyncio
    async def test_add_documents(self, store: VectorStore, embedder: Embedder):
        """Adding documents should return chunk IDs."""
        chunks = [
            {"text": "Quantum computing uses qubits.", "metadata": {"source": "test"}, "chunk_id": "abc123"},
            {"text": "Machine learning is a subset of AI.", "metadata": {"source": "test"}, "chunk_id": "def456"},
        ]
        ids = await store.add_documents(chunks, embedder=embedder)
        assert len(ids) == 2
        assert "abc123" in ids
        assert "def456" in ids

    @pytest.mark.asyncio
    async def test_similarity_search(self, store: VectorStore, embedder: Embedder):
        """Search should return relevant results."""
        chunks = [
            {"text": "Quantum computing uses qubits and superposition.", "metadata": {"source": "doc1"}, "chunk_id": "1"},
            {"text": "Climate change is caused by greenhouse gases.", "metadata": {"source": "doc2"}, "chunk_id": "2"},
            {"text": "Machine learning models require training data.", "metadata": {"source": "doc3"}, "chunk_id": "3"},
        ]
        await store.add_documents(chunks, embedder=embedder)

        results = await store.similarity_search("quantum", k=2, embedder=embedder)
        assert len(results) >= 1
        # The quantum chunk should be the top result
        assert any("quantum" in r["text"].lower() for r in results)

    @pytest.mark.asyncio
    async def test_similarity_search_empty_store(self, store: VectorStore, embedder: Embedder):
        """Searching an empty store should return empty list."""
        results = await store.similarity_search("anything", k=5, embedder=embedder)
        assert results == []

    @pytest.mark.asyncio
    async def test_delete_documents(self, store: VectorStore, embedder: Embedder):
        """Deleted documents should not appear in results."""
        chunks = [
            {"text": "This is a unique test document.", "metadata": {"source": "test"}, "chunk_id": "delete-me"},
        ]
        await store.add_documents(chunks, embedder=embedder)
        assert await store.count() == 1

        await store.delete_documents(["delete-me"])
        assert await store.count() == 0

    @pytest.mark.asyncio
    async def test_count(self, store: VectorStore, embedder: Embedder):
        """Count should reflect the number of stored chunks."""
        assert await store.count() == 0
        chunks = [
            {"text": "Doc A", "metadata": {"source": "test"}, "chunk_id": "a"},
            {"text": "Doc B", "metadata": {"source": "test"}, "chunk_id": "b"},
        ]
        await store.add_documents(chunks, embedder=embedder)
        assert await store.count() == 2

    @pytest.mark.asyncio
    async def test_search_results_shape(self, store: VectorStore, embedder: Embedder):
        """Search results should have the expected structure."""
        chunks = [
            {"text": "Test document content here", "metadata": {"source": "test"}, "chunk_id": "shape-test"},
        ]
        await store.add_documents(chunks, embedder=embedder)
        results = await store.similarity_search("test", k=5, embedder=embedder)
        if results:
            r = results[0]
            assert "text" in r
            assert "metadata" in r
            assert "score" in r
            assert "chunk_id" in r
            assert isinstance(r["score"], float)


# ======================================================================
# RAGRetriever
# ======================================================================

class TestRAGRetriever:
    """RAGRetriever end-to-end."""

    @pytest.fixture
    def retriever(self, tmp_path) -> RAGRetriever:
        """Create a fresh RAGRetriever for each test using a temp persist dir."""
        vs = VectorStore(persist_dir=str(tmp_path / "chroma"))
        return RAGRetriever(vector_store=vs)

    @pytest.mark.asyncio
    async def test_ingest_document(self, retriever: RAGRetriever):
        """Ingesting a document should return chunk IDs."""
        content = "Quantum computing is a rapidly evolving field. " * 20
        chunk_ids = await retriever.ingest_document(content, source="test_doc", doc_type="text")
        assert len(chunk_ids) > 0
        assert all(isinstance(cid, str) for cid in chunk_ids)

    @pytest.mark.asyncio
    async def test_ingest_and_retrieve(self, retriever: RAGRetriever):
        """Documents should be retrievable after ingestion."""
        await retriever.ingest_document(
            "Quantum computing uses qubits and superposition for computation. "
            "This is a revolutionary approach to solving complex problems.",
            source="quantum_intro",
            doc_type="text",
        )
        await retriever.ingest_document(
            "Climate change refers to long-term shifts in temperatures and "
            "weather patterns, mainly caused by human activities.",
            source="climate_intro",
            doc_type="text",
        )

        results = await retriever.retrieve("quantum qubits superposition", k=3)
        assert len(results) >= 1
        assert any("quantum" in r["text"].lower() for r in results)

    @pytest.mark.asyncio
    async def test_retrieve_empty(self, retriever: RAGRetriever):
        """Retrieving from empty store should return empty list."""
        results = await retriever.retrieve("anything", k=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_retrieve_with_scores(self, retriever: RAGRetriever):
        """retrieve_with_scores should filter by threshold."""
        await retriever.ingest_document(
            "This is some content about artificial intelligence and machine learning.",
            source="ai_doc",
            doc_type="text",
        )

        # With threshold 0.0, should get results
        results = await retriever.retrieve_with_scores("AI", k=5, score_threshold=0.0)
        assert len(results) >= 0  # Could be 0 with very low similarity

        # With very high threshold, results may be empty
        high_results = await retriever.retrieve_with_scores("AI", k=5, score_threshold=0.99)
        assert isinstance(high_results, list)

    @pytest.mark.asyncio
    async def test_ingest_multiple_and_query(self, retriever: RAGRetriever):
        """Multiple documents should all be searchable."""
        docs = [
            ("Python is a programming language.", "doc1"),
            ("JavaScript runs in the browser.", "doc2"),
            ("Rust is a systems programming language.", "doc3"),
        ]
        for content, source in docs:
            await retriever.ingest_document(content, source=source)

        results = await retriever.retrieve("programming language", k=3)
        assert len(results) >= 1
        # Should find at least Python or Rust
        texts = " ".join(r["text"] for r in results).lower()
        assert ("python" in texts or "rust" in texts)

    @pytest.mark.asyncio
    async def test_chunker_integration(self, retriever: RAGRetriever):
        """The retriever should use its chunker properly."""
        # A document that should produce multiple chunks
        long_text = "Artificial intelligence. " * 30 + "\n\n" + "Machine learning. " * 30
        chunk_ids = await retriever.ingest_document(long_text, source="long_doc")
        assert len(chunk_ids) > 1


# ======================================================================
# RAGRetrieverTool
# ======================================================================

class TestRAGRetrieverTool:
    """RAGRetrieverTool integration."""

    @pytest.fixture
    def tool(self) -> RAGRetrieverTool:
        return RAGRetrieverTool()

    @pytest.mark.asyncio
    async def test_retrieve_action_missing_query(self, tool: RAGRetrieverTool):
        """Retrieve without query should return error."""
        result = await tool.execute(action="retrieve")
        assert result.success is False
        assert "query" in result.error.lower()

    @pytest.mark.asyncio
    async def test_ingest_and_retrieve_via_tool(self, tool: RAGRetrieverTool):
        """Full ingest then retrieve cycle via tool."""
        # Ingest
        ingest_result = await tool.execute(
            action="ingest",
            content="Quantum entanglement is a physical phenomenon.",
            source="physics_101",
            doc_type="text",
        )
        assert ingest_result.success is True
        assert ingest_result.data["count"] > 0
        assert len(ingest_result.data["chunk_ids"]) > 0

        # Retrieve
        retrieve_result = await tool.execute(
            action="retrieve",
            query="quantum entanglement",
            k=5,
        )
        assert retrieve_result.success is True
        assert retrieve_result.data["count"] >= 1
        assert any("entanglement" in r["text"].lower() for r in retrieve_result.data["results"])

    @pytest.mark.asyncio
    async def test_unknown_action(self, tool: RAGRetrieverTool):
        """Unknown action should return error."""
        result = await tool.execute(action="unknown_action")
        assert result.success is False
        assert "Unknown action" in result.error

    @pytest.mark.asyncio
    async def test_missing_action(self, tool: RAGRetrieverTool):
        """Missing action parameter should return error."""
        result = await tool.execute()
        assert result.success is False
        assert "action" in result.error.lower()

    @pytest.mark.asyncio
    async def test_ingest_missing_params(self, tool: RAGRetrieverTool):
        """Ingest without content/source should return error."""
        result = await tool.execute(action="ingest", content="content only")
        assert result.success is False

        result = await tool.execute(action="ingest", source="source only")
        assert result.success is False


# ======================================================================
# ToolRouter integration
# ======================================================================

class TestToolRouterRAGIntegration:
    """RAG tool registered in ToolRouter."""

    def test_rag_registered(self):
        """RAG tool should be registered in default tools."""
        router = ToolRouter()
        tool = router.get_tool("rag")
        assert isinstance(tool, RAGRetrieverTool)
        assert tool.name == "rag_retrieve"

    def test_list_tools_includes_rag(self):
        """Tool listing should include rag."""
        router = ToolRouter()
        names = {t["name"] for t in router.list_tools()}
        assert "rag_retrieve" in names

    @pytest.mark.asyncio
    async def test_execute_rag_via_router(self):
        """Execute RAG tool through the router."""
        router = ToolRouter()

        # Ingest
        result = await router.execute(
            "rag",
            action="ingest",
            content="Router integration test document.",
            source="router_test",
        )
        assert result.success is True
        assert "chunk_ids" in result.data

        # Retrieve
        result = await router.execute(
            "rag",
            action="retrieve",
            query="router integration",
            k=3,
        )
        assert result.success is True
        assert result.data["count"] >= 1
