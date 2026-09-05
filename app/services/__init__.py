"""DeepResearch-Agent 的服务层模块。

提供 ReportService、ResearchService、LLMService、MemoryService 等业务服务。
"""

from app.services.report_service import ReportService
from app.services.research_service import ResearchService
from app.services.llm_service import LLMService
from app.services.query_router import QueryRouter
from app.services.direct_answer_service import DirectAnswerService

try:
    from app.memory.knowledge_memory import KnowledgeMemory
    from app.memory.session_memory import SessionMemory

    MemoryService = SessionMemory
except ImportError:
    MemoryService = None  # type: ignore[assignment,misc]

__all__ = [
    "ReportService",
    "ResearchService",
    "LLMService",
    "QueryRouter",
    "DirectAnswerService",
    "MemoryService",
]
