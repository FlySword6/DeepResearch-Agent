"""Application configuration using pydantic-settings."""

from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Global application settings loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # LLM API Keys
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    DEEPSEEK_API_KEY: Optional[str] = None
    DASHSCOPE_API_KEY: Optional[str] = None
    OPENAI_BASE_URL: Optional[str] = None
    DEEPSEEK_BASE_URL: Optional[str] = None
    EMBEDDING_API_KEY: Optional[str] = None
    EMBEDDING_BASE_URL: Optional[str] = None
    EMBEDDING_MODEL: Optional[str] = None

    # Model Selection
    LLM_MODEL_PLANNER: str = "gpt-4o"
    LLM_MODEL_RESEARCHER: str = "gpt-4o"
    LLM_MODEL_WRITER: str = "gpt-4o"
    LLM_MODEL_REVIEWER: str = "gpt-4o"

    # Search API
    SEARCH_API_PROVIDER: str = "tavily"
    SEARCH_BACKENDS: str = "tavily,duckduckgo,github"
    TAVILY_API_KEY: Optional[str] = None
    EXA_API_KEY: Optional[str] = None
    GITHUB_TOKEN: Optional[str] = None
    ENABLE_MOCK_SEARCH: bool = False
    SEARCH_MOCK_FALLBACK: bool = False

    # Storage
    REDIS_URL: str = "redis://localhost:6379/0"
    CHROMA_DB_PATH: str = "./data/chroma_db"
    RAG_INDEX_PATH: str = "./data/rag_index"

    # Hybrid RAG 配置
    RAG_VECTOR_BACKEND: str = "milvus"
    RAG_PARENT_CHUNK_SIZE: int = 1800
    RAG_PARENT_CHUNK_OVERLAP: int = 200
    RAG_CHILD_CHUNK_SIZE: int = 512
    RAG_CHILD_CHUNK_OVERLAP: int = 64
    RAG_VECTOR_TOP_K: int = 20
    RAG_BM25_TOP_K: int = 20
    RAG_RRF_K: int = 60

    # Milvus 向量库配置
    MILVUS_URI: str = "http://localhost:19530"
    MILVUS_TOKEN: Optional[str] = None
    MILVUS_COLLECTION: str = "research_knowledge"
    MILVUS_METRIC_TYPE: str = "COSINE"
    MILVUS_CONSISTENCY_LEVEL: str = "Bounded"
    MILVUS_TEXT_MAX_LENGTH: int = 16384
    MILVUS_METADATA_MAX_LENGTH: int = 8192
    MILVUS_QUERY_LIMIT: int = 10000

    # Tools
    ENABLE_PYTHON_TOOL: bool = False

    # Browser
    BROWSER_USE_PLAYWRIGHT: bool = True

    # 工作流引擎：langgraph | harness
    WORKFLOW_ENGINE: str = "langgraph"

    # 对话路由：简单问题直接搜索，复杂研究任务进入多 Agent
    QUERY_ROUTER_ENABLED: bool = True
    DIRECT_SEARCH_MAX_RESULTS: int = 5
    MULTI_AGENT_ROUTE_MIN_LENGTH: int = 180
    MULTI_AGENT_ROUTE_KEYWORDS: str = ""

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "info"

    # Execution
    RESEARCH_PARALLELISM: int = 3
    CONTEXT_MAX_CHARS: int = 60000

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/research.db"

    # Auth
    JWT_SECRET: str = "dev-secret-change-in-production"
    ENABLE_AUTH: bool = False

    # Optional observability
    LANGFUSE_ENABLED: bool = False
    LANGFUSE_PUBLIC_KEY: Optional[str] = None
    LANGFUSE_SECRET_KEY: Optional[str] = None
    LANGFUSE_HOST: Optional[str] = None

    # Per-task workspace uploads
    WORKSPACE_ROOT: str = "./data/workspaces"
    UPLOAD_MAX_FILES: int = 10
    UPLOAD_MAX_BYTES: int = 20 * 1024 * 1024
    UPLOAD_ALLOWED_EXTS: str = ".pdf,.md,.txt,.csv,.json,.docx"

    @model_validator(mode="after")
    def _check_production_security(self) -> "Settings":
        if self.ENABLE_AUTH and self.JWT_SECRET == "dev-secret-change-in-production":
            raise ValueError(
                "ENABLE_AUTH=true 时必须设置非默认的 JWT_SECRET（生产环境安全要求）"
            )
        return self


settings = Settings()
