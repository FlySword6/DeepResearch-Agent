# DeepResearch-Agent

> 基于多 Agent 协作的自动化研究分析系统

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-green)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2%2B-orange)](https://langchain-ai.github.io/langgraph)

---

## 项目简介

DeepResearch-Agent 是一个基于多 Agent 协作架构的自动化研究分析系统。用户输入研究课题，系统自动完成：任务拆解 → 资料搜索 → 网页深度阅读 → 知识整理 → 报告撰写 → 质量审查的完整闭环。

### 核心能力

| 能力 | 说明 |
|------|------|
| 🤖 多 Agent 协作 | Planner-Researcher-Writer-Reviewer 四 Agent 系统 |
| 🚦 对话智能路由 | 简单问题直接联网搜索回答，复杂调研任务进入多 Agent |
| 🔁 双工作流引擎 | 支持 LangGraph Workflow 与 Harness Agent Runtime 配置切换 |
| 🔧 插件式 Tool 系统 | 搜索、网页浏览、Python 执行等工具的灵活路由 |
| 🧠 Hybrid RAG 知识库 | BM25 + Milvus 向量检索 + RRF 融合，支持父子 chunk 上下文补全 |
| 💾 双记忆系统 | Session Memory（任务上下文）+ Knowledge Memory（跨任务知识） |
| 📊 结构化报告 | Markdown + PDF 双格式下载 |
| 🔍 自动质量审查 | Reviewer Agent 迭代评分优化，最多 3 轮 |
| ⚡ 实时流式输出 | SSE 实时展示 Agent 执行轨迹 |
| 🌓 深色/浅色主题 | 一键切换，自动记忆偏好 |
| 📚 知识库管理 | 文档导入、检索测试、引用来源列表 |

---

## 架构图

```
User → FastAPI → Query Router
                 ├── Direct Search Answer → SearchTool → 外部搜索
                 └── Workflow Engine(langgraph | harness) → Tool Router → 外部服务
                                      ├── LangGraph Workflow
                                      ├── Harness Agent Runtime
                                      ├── Planner / Researcher / Writer / Reviewer
                                      └── Hybrid RAG(BM25 + Milvus Vector + RRF + Parent-Child)
```

**工作流程：**

1. **Query Router** — 先判断问题是否命中“调研、调查、研究、趋势、发展”等复杂任务词
2. **Direct Search Answer** — 简单问题直接调用搜索工具并生成短答案
3. **Planner Agent** — 复杂任务进入多 Agent，拆解为可执行的子任务和研究计划
4. **Researcher Agent** — 执行搜索、浏览网页、读取文档，收集原始资料
5. **Writer Agent** — 基于收集的资料撰写结构化研究报告
6. **Reviewer Agent** — 对报告进行质量评分，触发最多 3 轮迭代优化

---

## 快速开始

### 前置条件

- Python >= 3.11
- Node.js >= 18（前端构建）
- Redis（可选，开发模式使用内存存储）
- Milvus（可选；Docker Compose 会自动启动，本地直跑时不可用会降级到 ChromaDB）

### 安装

1. 克隆仓库
```bash
git clone <repo-url>
cd deep-research-agent
```

2. 安装依赖
```bash
pip install -r requirements.txt
```

3. 配置环境变量
```bash
cp .env.example .env
# 编辑 .env 填入 API Key
```

4. 启动服务
```bash
uvicorn app.main:app --reload
```

5. （可选）构建前端
```bash
cd app/web
npm install
npm run build
```

6. 访问
- 生产模式（使用构建后的前端）: http://localhost:8000
- 开发模式（Vite 热更新）: `cd app/web && npm run dev` → http://localhost:5173
- API 文档: http://localhost:8000/docs

### Docker 部署

```bash
docker-compose up --build
```

Docker Compose 会同时启动 Redis、etcd、MinIO 和 Milvus Standalone。容器内默认使用：

```env
RAG_VECTOR_BACKEND=milvus
MILVUS_URI=http://milvus:19530
```

搜索后端可通过 `SEARCH_BACKENDS=tavily,duckduckgo,github,exa` 调整。默认 `ENABLE_MOCK_SEARCH=false`，当外部搜索源不可用时，系统会明确提示“未获得真实结果”，不会把 mock 占位数据写进报告。

本地直接运行 Python 时，如果没有启动 Milvus，RAG 会自动降级到 ChromaDB；需要强制使用 ChromaDB 时可设置：

```env
RAG_VECTOR_BACKEND=chroma
```

---

## 技术栈

### 后端

- **语言**: Python 3.11+
- **Web 框架**: FastAPI + Uvicorn
- **Agent 编排**: LangGraph + Harness Agent Runtime 双引擎
- **对话路由**: Query Router 规则判断 + Direct Search Answer 快速问答
- **LLM**: OpenAI / Anthropic API
- **搜索后端**: Tavily / DuckDuckGo / GitHub / Exa 可插拔配置，默认禁用 mock 搜索结果
- **RAG 检索**: Milvus 向量检索 + BM25 + RRF 融合 + 父子 chunk（ChromaDB 可作为本地兜底）
- **缓存**: Redis
- **浏览器**: Playwright / httpx+BeautifulSoup

### 前端

- **框架**: React 18 + Vite
- **样式**: Tailwind CSS + 深色/浅色主题切换
- **实时通信**: SSE (Server-Sent Events)
- **字体**: Geist Sans + Geist Mono
- **动画**: Motion
- **图标**: Phosphor Icons
- **特色功能**:
  - 深色/浅色一键切换，自动记忆偏好
  - Agent 执行轨迹实时时间线展示
  - 研究报告实时流式渲染
  - 可拖动浮动知识库管理窗口
  - 历史记录管理（刷新/批量删除）
  - 知识库检索测试

---

## API 文档

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/research` | 发起研究任务（支持 RAG 知识库开关） |
| GET | `/api/research/{id}/stream` | SSE 实时流，推送 agent_status / report_chunk / completed 等事件 |
| GET | `/api/research/{id}` | 查询任务状态 |
| GET | `/api/reports/{id}` | 获取报告文件（Markdown/PDF） |
| GET | `/api/history` | 历史任务列表（无分页限制，返回全部） |
| POST | `/api/reports/batch-delete` | 批量删除历史报告 |
| POST | `/api/knowledge/ingest` | 导入文档到知识库 |
| GET | `/api/knowledge/search` | 检索知识库 |
| GET | `/api/knowledge/list` | 知识库文档列表 |
| DELETE | `/api/knowledge/docs` | 删除知识库文档 |
| GET | `/health` | 健康检查 |

---

## 项目亮点

1. **双引擎多 Agent 架构**: 支持 `WORKFLOW_ENGINE=langgraph|harness` 配置切换。LangGraph 负责显式状态图编排，Harness Agent Runtime 负责顺序执行式 Agent 循环，复用同一套 Planner-Researcher-Writer-Reviewer 和 Tool 系统。

2. **对话智能路由**: 请求进入后先由 Query Router 做轻量判断。命中“调研、调查、研究、趋势、发展、分析、报告”等关键词时进入多 Agent；简单事实型问题直接联网搜索并输出答案，减少不必要的多 Agent 启动成本。

3. **插件式 Tool 系统**: 统一的 Tool Router 路由层，Agent 按需动态调用搜索、网页浏览、Python 执行等工具。新增工具只需继承 BaseTool 并注册，零侵入扩展。

4. **Hybrid RAG + 双记忆系统**: RAG 从单路 ChromaDB 向量检索升级为 Milvus 向量检索 + BM25 的混合召回，通过 RRF 融合排序；父子 chunk 机制用 child chunk 精准召回、parent chunk 补全上下文。Session Memory 保存任务上下文，Knowledge Memory 持久化研究成果实现跨任务复用。

5. **实时流式前端**: 基于 SSE 的 Agent 执行轨迹实时展示，研究报告流式渲染，深色/浅色主题一键切换，知识库窗口可拖动管理，历史记录支持批量操作。


## 近期新增功能

### 2026年8月 — Hybrid RAG 与双工作流引擎

- **对话智能路由**: 新增 Query Router，简单问题走 Direct Search Answer，复杂研究问题再进入多 Agent 工作流
- **双引擎切换**: 新增 `WORKFLOW_ENGINE=langgraph|harness`，保留 LangGraph 工作流，同时提供 Harness Agent Runtime 运行路径
- **Milvus 向量后端**: RAG 向量检索层支持 `RAG_VECTOR_BACKEND=milvus|chroma|auto`，默认优先 Milvus，连接失败时降级到 ChromaDB
- **Hybrid RAG**: 新增 BM25 关键词索引，与 Milvus 向量检索通过 RRF 融合排序
- **父子 chunk**: parent chunk 负责完整上下文，child chunk 负责精准检索，提升长文档引用质量
- **共享 RAG 实例**: API 知识库接口和 Agent RAG Tool 共用同一个检索器实例，内存兜底模式下也能保持一致

### 2026年7月 — 前端全面重构

- **深色科技风 UI**: 深色/浅色主题一键切换，偏好自动持久化
- **玻璃态设计**: `backdrop-filter` 玻璃面板 + 微光 border 效果
- **Geist 字体**: 替换默认字体，Geist Sans + Geist Mono 搭配
- **Agent 执行时间线**: Agent 状态 + 工具调用子事件分组 + 渐变进度条
- **研究报告渲染**: 代码块语言标签 + 引用侧栏 + MD/PDF 下载按钮统一样式
- **可拖动的知识库窗口**: 拖动标题栏任意移动，关闭按钮始终可见
- **历史记录管理**: 刷新 + 管理模式 + 勾选批量删除
- **RAG 知识库引用**: 报告末尾自动列出引用来源文档名称
- **修复**: fetchHistory 变量提升避免 TDZ 崩溃、RAG 检索缺少 action 参数、PDF 下载从 MD 回退改为报错提示、有序列表空行不中断序号、PDF 生成 bulletType 参数错误

---

## 项目结构

```
deep-research-agent/
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI 应用入口
│   ├── config.py                # 全局配置（pydantic-settings）
│   ├── middleware.py            # 中间件（日志、CORS、监控）
│   ├── agents/
│   │   ├── base.py              # Agent 基类
│   │   ├── planner.py           # Planner Agent：任务拆解与研究规划
│   │   ├── researcher.py        # Researcher Agent：资料搜索与收集
│   │   ├── writer.py            # Writer Agent：报告撰写
│   │   └── reviewer.py          # Reviewer Agent：质量审查与评分
│   ├── memory/
│   │   ├── session_memory.py    # Session Memory：单次任务上下文
│   │   └── knowledge_memory.py  # Knowledge Memory：跨任务知识复用
│   ├── models/
│   │   ├── state.py             # Agent 状态定义
│   │   ├── schemas.py           # Pydantic 请求/响应模型
│   │   ├── report.py            # 报告数据模型
│   │   └── tools.py             # Tool 调用数据模型
│   ├── rag/
│   │   ├── document_loader.py   # 文档加载器（PDF/MD/TXT/HTML）
│   │   ├── chunker.py           # 文档分块策略
│   │   ├── embedder.py          # 向量化嵌入
│   │   ├── vector_store.py      # ChromaDB 向量存储兜底
│   │   ├── milvus_store.py      # Milvus 向量存储
│   │   ├── bm25_store.py        # BM25 关键词索引
│   │   ├── parent_store.py      # 父块上下文存储
│   │   ├── service.py           # RAG 单例服务
│   │   └── retriever.py         # Hybrid RAG 检索器
│   ├── harness/
│   │   └── runtime.py           # Harness Agent Runtime
│   ├── services/
│   │   ├── llm_service.py       # LLM 调用封装（OpenAI/Anthropic）
│   │   ├── query_router.py      # 对话路由：简单问答 / 多 Agent 判断
│   │   ├── direct_answer_service.py # 简单问题直接联网搜索回答
│   │   ├── research_service.py  # 研究任务生命周期管理
│   │   └── report_service.py    # 报告生成（Markdown + PDF）
│   ├── tools/
│   │   ├── base.py              # BaseTool 基类
│   │   ├── search.py            # 搜索工具（Tavily）
│   │   ├── browser.py           # 网页浏览工具
│   │   ├── python_executor.py   # Python 代码执行工具
│   │   ├── memory.py            # 记忆读写工具
│   │   ├── rag_retriever.py     # RAG 检索工具
│   │   └── router.py            # Tool Router 路由层
│   ├── utils/
│   │   ├── llm.py               # LLM 工具函数
│   │   ├── logger.py            # 结构化日志
│   │   ├── markdown_utils.py    # Markdown 处理工具
│   │   └── pdf_utils.py         # PDF 生成工具（ReportLab）
│   ├── workflow/
│   │   ├── engine.py            # LangGraph / Harness 引擎分发
│   │   ├── graph.py             # LangGraph 工作流图定义
│   │   ├── nodes.py             # 工作流节点函数（含 RAG 引用来源收集）
│   │   ├── conditions.py        # 条件路由函数
│   │   └── events.py            # 事件发布机制
│   └── web/                     # React 前端
│       ├── index.html
│       ├── package.json
│       ├── vite.config.js
│       ├── tailwind.config.js
│       ├── postcss.config.js
│       └── src/
│           ├── main.jsx
│           ├── App.jsx          # 主应用（深色/浅色主题、历史管理）
│           ├── index.css         # 设计令牌、玻璃态样式、动效
│           ├── hooks/useSSE.js   # SSE 连接 Hook
│           ├── contexts/
│           └── components/
│               ├── InputPanel.jsx    # 研究输入面板（RAG 开关、知识库弹窗）
│               ├── AgentTrace.jsx    # Agent 执行轨迹时间线
│               └── ReportViewer.jsx  # 报告展示（引用侧栏、MD/PDF 下载）
├── data/
│   ├── chroma_db/               # ChromaDB 兜底持久化数据
│   ├── milvus_lite.db           # Milvus Lite 本地数据（可选）
│   ├── knowledge/               # Knowledge Memory 存储
│   ├── reports/                 # 生成的报告文件
│   └── uploads/                 # 用户上传文件
├── tests/
│   ├── conftest.py              # 测试配置与 Fixtures
│   ├── test_agents.py           # Agent 单元测试
│   ├── test_memory.py           # 记忆系统测试
│   ├── test_rag.py              # RAG 系统测试
│   ├── test_tools.py            # Tool 系统测试
│   ├── test_workflow.py         # 工作流测试
│   ├── test_report_service.py   # 报告服务测试
│   ├── test_research_service.py # 研究服务测试
│   ├── test_middleware.py       # 中间件测试
│   ├── test_logger.py           # 日志测试
│   ├── test_markdown_utils.py   # Markdown 工具测试
│   └── test_pdf_utils.py        # PDF 工具测试
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── pyproject.toml
├── .env.example
├── .gitignore
└── README.md
```

---

## 测试

项目包含 **207 个测试用例**，覆盖核心功能模块：

```bash
# 运行全部测试
pytest tests/ -v

# 运行特定模块测试
pytest tests/test_agents.py -v
pytest tests/test_workflow.py -v
pytest tests/test_rag.py -v

# 运行测试并生成覆盖率报告
pytest tests/ --cov=app --cov-report=term-missing
```

---

## 许可证

MIT
