# LangGraph 与 Harness Agent Runtime 双引擎对比

## 背景

多 Agent 系统通常需要在“显式工作流”和“运行时 Agent 循环”之间做取舍。LangGraph 适合把任务拆成固定节点和条件边，状态变化清晰，便于调试与恢复。Harness Agent Runtime 更适合将 Agent、工具和执行策略封装为运行时能力，便于在不同工作流中复用。

## LangGraph 路线

LangGraph 的优势是状态图清晰。Planner、Researcher、Writer、Reviewer 可以作为节点接入，节点之间通过条件函数决定是否进入下一轮迭代。例如 Reviewer 给出低分时，工作流可以回到 Researcher 或 Writer 继续优化。对于需要可视化、断点恢复和严格流程控制的深度研究任务，LangGraph 更容易解释和维护。

## Harness 路线

Harness Agent Runtime 的优势是运行时抽象更统一。它可以把 Agent 执行、工具调用、事件发布和错误处理封装到同一层，使上层业务只关心输入任务和最终结果。如果未来要支持更多 Agent 编排策略，Harness 可以作为运行时适配层，降低对单一工作流框架的绑定。

## 双引擎切换价值

双引擎切换的核心不是让两个框架同时工作，而是让系统具备演进空间。开发阶段可以用 LangGraph 验证规划、检索、撰写、审查四阶段流程；当系统需要接入更多执行策略时，可以切换到 Harness Runtime。配置项 WORKFLOW_ENGINE=langgraph 或 WORKFLOW_ENGINE=harness 可以控制实际执行路径。

## 结论

对于简历项目和教学项目，保留 LangGraph 作为主路线更容易展示多 Agent 工作流设计；同时提供 Harness Runtime 作为可切换执行层，可以体现架构扩展性和工程抽象能力。
