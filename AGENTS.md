# Agent 执行规范 (Agent Execution Standards)

## 核心原则
1. **唯一事实来源 (Source of Truth)**: `youtube-video-translator/references/phases.md` 是定义流水线阶段和任务委派的最终权威。
2. **逻辑解耦 (Decoupled Orchestration)**: Python `phase_runner.py` 仅负责管理数据流转和状态迁移，**严禁**在代码中硬编码具体的业务逻辑。
3. **子代理委派 (Sub-agent Delegation)**: 所有定义为 Agent 的任务（如 `youtube-video-translator/agents/uploader.md`）均由子代理执行。Runner 的职责是委派任务，而非复现逻辑。

## 集成模式 (Integration Pattern)
- **Runner 职责**: 当 `phase_runner.py` 运行到标记为 Agent 的阶段时，输出明确的执行指令并暂停或退出。
- **执行流程**:
  1. Runner 完成状态处理 (阶段 N-1)。
  2. Runner 输出: `Action: Please spawn subagent using agents/[agent].md`
  3. 用户/CLI 触发: `@generalist 执行 agents/[agent].md，上下文为 [ID]`。
- **设计初衷**: 确保 `agents/` 下的 Markdown 指令是维护的唯一入口。业务逻辑的演进只需更新 Markdown 指令，无需触碰 Python 代码，保持流水线稳定。

## 维护准则
- 确保 `agents/` 下的指令文档自成体系（包含契约、工作流、质量门禁）。
- 若 Agent 任务逻辑发生变化，仅需更新对应的 Markdown 文档，集成层无需变更。
