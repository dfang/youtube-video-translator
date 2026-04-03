结合 skill-creator 的 pattern，有几个关键改动可以解决长时间 session 丢上下文的问题：

---

1. 引入状态文件 + 断点续跑

每个 phase 完成后写一个 checkpoint：

// translations/[VIDEO_ID]/.phase-state.json
{
"video_id": "abc123",
"current_phase": 4,
"phase4_status": "in_progress",
"completed_phases": [0, 1, 2, 3],
"artifacts": {
"raw_video": "temp/raw_video.mp4",
"en_original": "temp/en_original.srt",
"zh_translated": "temp/zh_translated.srt"
}
}

主 session 重启时读这个文件，只从 current_phase 继续，所有前置 phase 的产出已经在磁盘上了。

---

2. Phase 级别的 Subagent 封装

每个 phase 的执行逻辑封装成独立 agent，contract 是文件输入/输出：

Phase 4 例子：
输入: temp/en_audited.srt
temp/batch_N.txt
输出: temp/batch_N.translated.srt

主 agent 只负责调度，不做具体翻译。这样即使 subagent 超时，也只丢一个 batch，不丢整个 phase。

参考 skill-creator/agents/grader.md 的做法，给每个 phase 写一个 agent 定义文件，放在
youtube-video-translator/agents/ 目录。

---

3. Phase-level Review（可选）

每个 phase 完成后，用类似 eval-viewer 的思路生成一个简报：

Phase 4 完成:

- 12 个 batch，11 个通过验证，1 个重试
- 总 token 消耗: ~500k
- 译文预览: temp/zh_translated.srt

这样用户可以在中途介入，而不是等到最后才发现问题。

---

4. 重构建议的目录结构

youtube-video-translator/
├── SKILL.md # 主 Orchestrator（精简，只负责调度）
├── agents/
│ ├── translator.md # Phase 4 翻译子agent 指令
│ ├── transcriber.md # Phase 3 语音转写指令
│ └── publisher.md # Phase 9 B站发布指令
├── scripts/
│ ├── phase_runner.py # 统一 phase 调度器（含 checkpoint 逻辑）
│ ├── state_manager.py # 读写 .phase-state.json
│ ├── env_check.py
│ ├── downloader.py
│ ├── whisperx_transcriber.py
│ ├── subtitle_splitter.py
│ ├── srt_to_ass.py
│ ├── voiceover_tts.py
│ ├── cover_generator.py
│ ├── video_muxer.py
│ └── cleaner.py
└── references/
├── filebin.md
└── ass_template.txt

核心思路：SKILL.md 变成一个薄薄的 orchestrator，真正逻辑都在 scripts/ 里，状态都在文件里。

---

5. 关键改动：Phase Runner

phase_runner.py 目前只管 Phase 4，建议扩展成通用调度器：

# phase_runner.py

# python phase_runner.py run-phase 4 --video-id abc123

def run_phase(phase, video_id):
state = load_state(video_id)
if phase <= state["current_phase"]:
print(f"Phase {phase} already completed, skipping")
return

      # 加载对应 agent 定义
      agent_md = load_agent(f"agents/phase{phase}.md")

      # 启动 subagent 执行
      # ...

      # 更新 state
      save_state(video_id, phase)

这样每个 phase 都可以独立 subagent 化，主 session 只负责任务分发和状态追踪。

---

## 完成状态 ✅

- [x] `scripts/state_manager.py` — 状态读写、checkpoint、断点续跑
- [x] `scripts/phase_runner.py` — 统一调度器，支持 `run --video-id` 和 `run --phase N`
- [x] `agents/translator.md` — Phase 4 翻译子agent
- [x] `agents/transcriber.md` — Phase 3 转写子agent
- [x] `agents/publisher.md` — Phase 9 发布子agent
- [x] `SKILL.md` — 精简为 orchestrator（~120行），真正逻辑下沉到 scripts/

## 待验证

- [x] `state_manager.py` 在空目录首次运行时的行为 — ✅ 已修复 CLI 解析 bug，验证通过
- [x] `phase_runner.py` 与现有 `phase4_runner.py` 的兼容性测试 — ✅ `phase_runner.py` 现在能正确调用 `phase4_runner.py`，并处理 batch 循环
- [x] subagent dispatch 文件 contract — ✅ agents/*.md 文件 contract 已定义，phase_runner.py 提供状态管理，SKILL.md 指导主 agent 何时调用 subagent

## 修复记录

- [x] `state_manager.py` CLI: `sys.argv[2]` → `sys.argv[1]` for video_id (`sys.argv[2]` for action)
- [x] `phase_runner.py`: Phase 0 添加 `python3` 前缀（shebang 问题）
- [x] `phase_runner.py`: SKILL_ROOT 添加本地开发路径 fallback
- [x] `phase_runner.py`: 修复 SKILL_ROOT 解析 — 优先 dev checkout（当 agents/ 存在）
- [x] `phase_runner.py`: Phase 4 完整翻译循环（start → check → finalize 或 interactive）
- [x] `whisperx_transcriber.py`: 添加 ICU 术语词典 + `WHISPERX_INITIAL_PROMPT` 环境变量扩展支持
