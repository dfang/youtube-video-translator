# YouTube Translator Pipeline 改造计划

## Summary

- 以 `review.md` 的建议为准，把当前实现从“阶段式大 Skill”收敛为“状态驱动 orchestrator + 原子能力流水线”。
- 保留现有 10 阶段、磁盘断点续传和 `phase_runner.py` 入口不变，避免打断现有使用方式；重点重构 Phase 3/4 的内部职责边界。
- 本文档面向当前仓库实施，不是纯方案文档；要求落到脚本拆分、持久化产物、失败恢复、测试和文档同步。

## Key Changes

### 1. Orchestrator 层

- 保留 `youtube-video-translator/SKILL.md` 作为唯一入口，但改写为“指令引导式 orchestrator”，不再把字幕获取、转写、分块、翻译、对齐混成一个大步骤。
- 保留 `youtube-video-translator/scripts/phase_runner.py` 作为稳定 CLI；内部改成调用原子模块，并把每一步的输入/输出写入磁盘状态。
- 明确约束：不做物理嵌套 Skill；允许 orchestrator 通过脚本和 subagent 调度原子能力。
- Orchestrator 每完成一个步骤（phase 或 chunk）都输出进度日志（如 `Processing: 12 / 58 chunks...`），便于用户感知进度和中断后定位。

### 2. Pipeline 拆分

- Phase 3 拆成 `metadata probe + caption discovery + raw video download`，输出明确元数据，不再只靠下载脚本隐式判断。
- Phase 4 拆成 `caption fetch（官方字幕） / audio extract（无字幕路径） / ASR / chunk build / translate / align / export` 七段，统一以”带时间戳的 segment”作为中间事实来源。
- 分块必须基于字幕段和时间范围，不允许只按裸文本切块；翻译必须 `chunk-by-chunk`，可并行，可单块重试，可校验后再合并。
- 翻译调度器（`translate_scheduler`）通过 subagent 并行处理多个 chunk，每个 chunk 的翻译状态（`status`、`attempts`）写回 `chunks.json`；并行度可配置（默认 4），单个 chunk 失败不影响其他 chunk。
- 翻译一致性保障：`glossary_terms` 在 `chunks.json` 里声明，translate_scheduler 翻译每个 chunk 前将其注入 prompt；用户也可在 `temp/glossary.json`（格式：`[{"term": "AI", "translation": "人工智能"}, ...]`）预定义术语表，chunk_build 时合并进 `chunks.json` 的 `glossary_terms` 字段。全局上下文（标题 + 简介 + 前序 chunk 尾句）在 `translation_state.json` 的 `prompt_version` 变更时自动失效，强制重新翻译。
- 对齐与导出从翻译阶段独立出来，统一产出 canonical subtitle manifest，再导出 SRT/VTT/ASS，Phase 7 只消费 canonical 字幕产物。

### 3. 持久化接口与状态

- 新增明确中间产物：
  - `temp/metadata.json`
  - `temp/caption_plan.json`
  - `temp/source_segments.json`
  - `temp/asr_segments.json`
  - `temp/chunks.json`
  - `temp/glossary.json`（可选，用户预定义术语表）
  - `temp/translation_state.json`
  - `temp/subtitle_manifest.json`
- `metadata.json` 至少包含：`video_id`、`title`、`duration`、`has_official_caption`、`caption_languages`。
- `caption_plan.json` 至少包含：`source` (`official|asr`)、`reason`、`input_srt`（官方路径时存在，ASR 路径时为 null）。
- `source_segments.json` 是进入 chunking 前的统一 segment 契约；无论来源是官方字幕还是 ASR，都必须先归一化写入该文件，再进入后续 chunk / align / export 流程。
- `source_segments.json` 与 `asr_segments.json` 至少包含：`start`、`end`、`text`（时间轴不可丢失，任何中间模块不得丢弃 start/end）。
- `chunks.json` 至少包含：`chunk_id`、`segment_ids`、`start`、`end`、`text`、`status`、`attempts`、`glossary_terms`（可选，翻译时注入一致性上下文）。
- `glossary.json`（可选）格式为 `[{"term": "原文", "translation": "译文"}, ...]`，chunk_build 时与用户预定义术语表合并写入各 chunk 的 `glossary_terms`。
- `translation_state.json` 至少包含：`model_id`、`prompt_version`、`glossary_hash`、`chunking_hash`、`source_hash`、`validator_version`；缓存命中必须以这些字段组成的 translation contract 为前提，不允许跨 contract 复用旧 chunk 结果。
- `subtitle_manifest.json` 至少包含：`start`、`end`、`source_text`、`translated_text`、`segment_id`。
- 失败恢复规则固定为“只重跑未完成或校验失败的最小单元”，禁止因为单个 chunk 失败而整段 Phase 4 全量重来。

### 4. Provider 与可扩展性

- 抽象四类 provider：字幕来源、ASR、翻译、TTS；默认实现继续使用当前仓库已有工具链。
- 当前默认映射：
  - `yt-dlp` 负责 metadata/caption
  - WhisperX 负责 ASR
  - 会话主模型负责翻译
  - 现有 TTS 脚本负责配音
- 翻译模型策略：默认始终使用当前会话 / channel 的 primary model；只有用户显式选择外部 provider 或显式启用成本优先模式时，才允许切换到其他模型。所选 provider、model 和策略必须持久化到 `temp/translation_state.json`，保证恢复执行时行为确定。
- 发布、封面、预览上传继续保留在后续 phase，但只能消费上游稳定产物，不允许在这些 phase 里重新推断标题、字幕来源或翻译状态。

### 5. Out of Scope（明确不做）

- 不做多语言字幕同时输出（当前仅支持中文目标语言）。
- 不做 ASR provider 的动态切换（WhisperX 固定为 ASR 默认实现）。
- 不做翻译结果的人工审核 UI 或 workflow。
- 不做跨视频的术语库持久化（glossary 仅在单次视频翻译流程内生效）。
- 不做 phase_runner 以外的第二套入口（不新增第二个 CLI 或 Web UI）。

### 6. Error Handling 策略

- 每个脚本（phase_*.py）在入口统一处理异常：失败时写入 `temp/<phase>_error.json`（含 `script`、`phase`、`error`、`timestamp`），状态机读到 error 文件则中止并透传错误，不做隐式重试。
- 单 chunk 翻译失败：状态写 `failed` + `error` 到 `chunks.json`，不影响其他 chunk；重跑时只调度 `status=failed` 的 chunk。
- 校验器失败：写 `temp/validation_errors.json`，phase_runner 检测到该文件则退出码非零，不进入下一 phase。
- 网络/IO 临时错误（ yt-dlp 下载中断、WhisperX 超时）：脚本内部最多重试 3 次，间隔 5s/10s/30s 指数退避；3 次后仍失败则写入 error 文件并退出。
- 所有 error 文件必须在 orchestrator 重跑前手动清除，或调用 `phase_runner.py cleanup --phase N` 清除指定 phase 的错误状态。

### 7. 文档与迁移

- 同步更新 `SKILL.md`、需求文档和 `changelog.md`，使”用户看到的 phase 描述”与”脚本实际职责”一致。
- 在文档中补齐 chunk 并行、失败恢复、进度反馈、字幕一致性、时间轴不可丢失等规则，避免后续实现回退成巨型步骤。

## Implementation Sequence

### Step 1 — 中间产物 JSON Contract（交付物：8 个 schema 文件）
- 在稳定仓库路径 `youtube-video-translator/references/schemas/` 下创建 8 个 `.schema.json` 文件，分别定义 `intent`、`metadata`、`caption_plan`、`source_segments`、`asr_segments`、`chunks`、`translation_state`、`subtitle_manifest` 的必填/可选字段（`glossary.json` 为用户输入，无需 schema）。
- 每个 schema 文件含 `required` 字段和时间轴约束注释（`start/end 不可丢失`）。
- `translations/[VIDEO_ID]/temp/` 只用于运行时产物，不存放 repo-owned schema 或其他静态契约文件。
- `intent.schema.json` 用于约束 Phase 1 写入的 `temp/intent.json`，避免在 `SKILL.md` 中内联维护第二份 schema。
- 验收：8 个 schema 文件可被 JSON Schema 校验工具解析，且 `source_segments.json` schema 能同时接纳官方字幕归一化结果和 ASR 结果（两种路径的输出兼容同一契约）。

### Step 2 — Phase 3 重构（交付物：拆分为 3 个独立脚本）
- `scripts/phase_3_metadata_probe.py`：调用 yt-dlp，输出 `temp/metadata.json`，含 `has_official_caption` 判断。
- `scripts/phase_3_caption_discovery.py`：读取 metadata，决定走 `official` 还是 `asr` 路径，输出 `temp/caption_plan.json`。
- `scripts/phase_3_video_download.py`：下载原始视频，输出 `temp/video.mp4`。
- 验收：`phase_runner.py run --video-id xxx --phase 3` 能完整执行三步且写足 metadata.json 和 caption_plan.json。

### Step 3 — Phase 4 前半段（交付物：caption_fetch + audio_extract + asr + asr_normalize）
- `scripts/phase_4_caption_fetch.py`：官方字幕路径，调用 yt-dlp 拉字幕，归一化直接写入 `temp/source_segments.json`（不走 asr_segments 中转）。
- `scripts/phase_4_audio_extract.py`：仅 ASR 路径专用，从 `temp/video.mp4` 提取标准化音频，输出 `temp/source_audio.wav`；该文件作为后续 ASR 的唯一输入，也可供重试或替换 ASR provider 时复用。
- `scripts/phase_4_asr.py`：ASR 路径，仅读取 `temp/source_audio.wav` 并调用 WhisperX 转写，输出 `temp/asr_segments.json`；不再负责 ffmpeg 提取音频。
- `scripts/phase_4_asr_normalize.py`：仅 ASR 路径专用，读取 `temp/asr_segments.json` 并归一化到 `temp/source_segments.json`，与 caption_fetch 的输出 schema 完全一致，确保后续 chunks.json 共用同一分块逻辑。
- 验收：同一视频走两条路径生成的 `source_segments.json` 文件结构和字段完全一致，可共用同一 `temp/chunks.json` 后续流程；删除 `temp/asr_segments.json` 后可仅重跑 ASR，不必重新抽音频；ffmpeg 失败与 WhisperX 失败在状态和错误文件中可明确区分。

### Step 4 — Phase 4 分块与翻译状态机（交付物：chunking + translate_scheduler + Provider 接口）
- `scripts/phase_4_chunk_build.py`：读取 `temp/source_segments.json`，按时间范围 + 字幕段边界分块，输出 `temp/chunks.json`（含 chunk_id、segment_ids、start、end、text、status=pending）。
- Provider 接口定义（先于调度器）：四类 provider（caption/ASR/translator/TTS）各一个接口文件（如 `providers/base.py`），translator 接口含 `translate(text, glossary, context) → str` 方法签名。
- `scripts/phase_4_translate_scheduler.py`：读取 `temp/chunks.json`，并行（默认 4）调度 subagent 翻译每个 chunk；每个 subagent 拿到该 chunk 的 `text` 和 `glossary_terms`（来自 `chunks.json`），连同全局上下文（视频标题、简介、前序 chunk 尾句）一起组成 prompt，调用 translator provider 接口；每个 chunk 完成后写回 `status=completed` 和 `attempts`；失败写 `status=failed` + `error`。
- `scripts/phase_4_validator.py`：在所有 chunk 翻译完成后一次性校验（不是逐 chunk 校验），检查范围：不缺块、序号连续、时间轴不漂移、疑似未翻译文本；校验失败写 `temp/validation_errors.json` 并阻止进入 align 阶段。
- 验收：单个 chunk 失败只重跑该 chunk，其他 chunk 不受影响；并行度可通过 `CHUNK_PARALLELISM` 环境变量配置；translator provider 可切换实现而不改调度器代码。

### Step 5 — Phase 4 后半段（交付物：align/export）
- `scripts/phase_4_align.py`：读取 `temp/source_segments.json` + `temp/chunks.json`，按 segment_ids 对齐翻译结果，输出 `temp/subtitle_manifest.json`。
- `scripts/phase_4_export.py`：读取 `temp/subtitle_manifest.json`，导出 SRT/VTT/ASS，支持双语/仅中文两种布局。
- 验收：导出文件时间轴与 source_segments 误差 < 0.1s。

### Step 6 — 封面、预览、发布 Phase 适配新产物 + 文档（交付物：Phase 5-10 适配 + 文档更新）
- Phase 5-10 全部改为消费 `temp/subtitle_manifest.json` 和 `temp/metadata.json`，不再重新推断字幕来源或翻译状态。
- Phase 9（发布）增加 `draft` 路径和正式路径两套检查逻辑。
- 更新 `SKILL.md`、`changelog.md`、内部 README，确保 phase 描述与脚本实际职责一致。
- 验收：`phase_runner.py run --video-id xxx --phase 9` 在缺少最终视频时明确报错，不静默失败。

## Test Plan

### 核心路径测试

- **T1（official 路径）**：用带官方字幕的 YouTube 视频跑完全流程，验证 `has_official_caption=true` 时跳过 ASR，最终 `subtitle_manifest.json` 的 `start/end` 与官方字幕时间轴误差 < 0.1s。
- **T2（ASR 路径）**：用无字幕视频跑，验证 `asr_segments.json` 含 `start/end/text`，`source_segments.json` 成功归一化，后续分块和翻译流程正常。
- **T3（单 chunk 失败恢复）**：在 Phase 4 翻译阶段模拟第 3 个 chunk 失败，验证：其他 chunk 状态保持 `completed`、第 3 个 chunk 状态为 `failed`、重跑后仅第 3 个重新翻译。
- **T4（校验器拦截）**：注入缺块、序号错乱（如 chunk_id 跳跃）、时间轴漂移（相邻 chunk 重叠 > 0.5s）、疑似未翻译文本（翻译文本与原文相同率 > 80%），验证校验器全部拦截并报错。
- **T5（双语/仅中文导出）**：同一 `subtitle_manifest.json` 分别以 bilingual 和 zh-only 布局导出 SRT，验证两种布局时间轴完全一致，仅文本内容不同。
- **T6（断点续传）**：在 Phase 4 翻译进行到一半时中断，重跑 `--phase 4`，验证：已完成 chunk 不重新翻译，进度从中断点继续，日志显示 `Resuming from chunk N / M`。
- **T7（Phase 7 消费 canonical 产物）**：用 `temp/subtitle_manifest.json` 和 `temp/video.mp4` 执行 Phase 7，验证生成视频含正确字幕轨道。
- **T8（Phase 9 阻塞）**：在缺少最终视频时执行 Phase 9，验证明确报错而非静默通过；`draft` 路径和正式发布路径各验证一次。
- **T9（Provider 切换）**：将 translator provider 从 Claude Opus 切换到自定义接口实现，验证其他 phase 脚本不变，仅 provider 配置变更。
- **T10（Schema 验证）**：用 JSON Schema 校验工具验证所有中间产物文件均符合对应 `.schema.json`，无冗余字段污染。

## Assumptions

- 这份 `plan.md` 默认是当前仓库的实施计划，而不是单独 PRD。
- 保留现有 10 阶段用户体验和 `phase_runner.py run --video-id ... [--phase N]` 调用方式，不做破坏性入口变更。
- 采用“指令引导 + 原子模块 + subagent”的方式协作，不创建嵌套 Skill 目录结构。
- 当前未找到 `RTK.md`，本计划仅基于仓库现状、`review.md` 和现有 `SKILL.md` / `scripts` 约束整理。
