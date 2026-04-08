# YouTube 视频翻译 Skill 需求规格说明书 (YouTube Translator Skill Requirements) - V4

本文件定义当前仓库中 YouTube 视频翻译能力的目标架构、阶段职责、状态产物、错误恢复策略，以及 Bilibili 发布约束。本文档与 `plan.md`、`youtube-video-translator/SKILL.md` 保持一致，作为后续实现和评审的统一基线。

## 1. 核心架构

该 Skill 采用 **状态驱动的单入口 orchestrator** 模式：

- 唯一稳定入口为 `youtube-video-translator/scripts/phase_runner.py`。
- 不使用物理嵌套子 Skill 目录；原子能力通过脚本和 subagent 协作完成。
- 所有阶段均围绕 `translations/[VIDEO_ID]/` 下的磁盘状态运行，支持断点续传和最小单元重试。
- 保留现有 10 个阶段的用户体验，但重点重构 Phase 3 和 Phase 4 的内部职责边界。

### 1.1 总体阶段

1. 环境检查
2. 收集用户意图
3. 元数据探测 + 字幕路径判定 + 视频下载
4. 字幕获取 / 抽音频 / ASR / 分块 / 翻译 / 对齐 / 导出
5. 中文配音
6. 封面生成
7. 最终视频合成
8. 预览上传
9. Bilibili 发布
10. 清理

## 2. Phase 3/4 原子能力拆分

### 2.1 Phase 3: Metadata + Caption Discovery + Video Download

Phase 3 必须拆成 3 个原子步骤：

- `phase_3_metadata_probe`
  - 输入：YouTube URL
  - 输出：`temp/metadata.json`
  - 职责：仅探测视频元数据和字幕可用性，不做后续处理
- `phase_3_caption_discovery`
  - 输入：`temp/metadata.json` + `subtitle_mode`
  - 输出：`temp/caption_plan.json`
  - 职责：只负责判断走 `official` 还是 `asr` 路径
- `phase_3_video_download`
  - 输入：YouTube URL
  - 输出：`temp/video.mp4`
  - 职责：只负责下载原始视频

### 2.2 Phase 4: Subtitle Pipeline

Phase 4 必须拆成 7 个原子步骤：

1. `phase_4_caption_fetch`
   - 官方字幕路径
   - 输出：`temp/source_segments.json`
2. `phase_4_audio_extract`
   - 无字幕路径
   - 输出：`temp/source_audio.wav`
3. `phase_4_asr`
   - 无字幕路径
   - 输入：`temp/source_audio.wav`
   - 输出：`temp/asr_segments.json`
4. `phase_4_asr_normalize`
   - 无字幕路径
   - 输入：`temp/asr_segments.json`
   - 输出：`temp/source_segments.json`
5. `phase_4_chunk_build`
   - 输入：`temp/source_segments.json`
   - 输出：`temp/chunks.json`
6. `phase_4_translate_scheduler`
   - 输入：`temp/chunks.json`
   - 输出：更新后的 `temp/chunks.json` + `temp/translation_state.json`
7. `phase_4_align` + `phase_4_export`
   - 输入：`temp/source_segments.json` + `temp/chunks.json`
   - 输出：`temp/subtitle_manifest.json`、SRT/VTT/ASS

### 2.3 设计原则

- 分块必须基于时间轴和字幕段边界，不能只按裸文本切分。
- 翻译必须 `chunk-by-chunk`，不可一次性翻完整视频。
- 官方字幕和 ASR 两条路径必须在进入 chunking 前统一归一化为同一个 `source_segments.json` 契约。
- 抽音频必须独立于 ASR，避免 ffmpeg 失败与 WhisperX 失败耦合。
- 对齐和导出必须独立于翻译步骤，避免格式导出逻辑反向污染翻译阶段。

## 3. 状态产物与契约

### 3.1 路径约束

- 运行时状态目录：`translations/[VIDEO_ID]/temp/`
- 最终输出目录：`translations/[VIDEO_ID]/final/`
- 静态 schema 路径：`youtube-video-translator/references/schemas/`

静态 schema 属于仓库资产，不能与每个视频实例的 `temp/` 运行时产物混放。

### 3.2 Canonical Artifacts

- `temp/intent.json`
  - Phase 1 用户意图产物
  - 必须满足 `references/schemas/intent.schema.json`

- `temp/metadata.json`
  - 至少包含：`video_id`、`title`、`duration`、`has_official_caption`、`caption_languages`
- `temp/caption_plan.json`
  - 至少包含：`source` (`official|asr`)、`reason`、`input_srt`
- `temp/source_audio.wav`
  - ASR 唯一输入音频，供重试与调试复用
- `temp/asr_segments.json`
  - 原始 ASR 结果，至少包含：`start`、`end`、`text`
- `temp/source_segments.json`
  - 统一 segment 契约；无论官方字幕还是 ASR，进入 chunking 前都必须写成这个格式
- `temp/chunks.json`
  - 至少包含：`chunk_id`、`segment_ids`、`start`、`end`、`text`、`status`、`attempts`、`glossary_terms`
- `temp/glossary.json`
  - 可选，用户输入术语表，格式：`[{"term": "原文", "translation": "译文"}]`
- `temp/translation_state.json`
  - 至少包含：`model_id`、`prompt_version`、`glossary_hash`、`chunking_hash`、`source_hash`、`validator_version`
- `temp/subtitle_manifest.json`
  - 至少包含：`start`、`end`、`source_text`、`translated_text`、`segment_id`

### 3.3 Translation Contract

翻译缓存只能在 translation contract 一致时复用：

- `model_id`
- `prompt_version`
- `glossary_hash`
- `chunking_hash`
- `source_hash`
- `validator_version`

只要上述任一字段变化，就不能静默复用旧的 chunk 翻译结果。

## 4. 模型与 Provider 策略

### 4.1 默认策略 (A-mode)

- 字幕翻译默认使用当前会话 / 当前 channel 的 primary model。
- 不应在默认路径中强制要求外部 API Key。
- 仅当用户明确选择外部 provider（如 Gemini/OpenAI）时，才提示对应 API Key。
- 恢复执行时必须沿用 `temp/translation_state.json` 中持久化的 provider/model 策略，不能在中途自动漂移。

### 4.2 可扩展 Provider

需要预留四类 provider 抽象：

- caption provider
- ASR provider
- translator provider
- TTS provider

当前默认实现：

- `yt-dlp` 负责 metadata/caption
- WhisperX 负责 ASR
- 当前会话主模型负责翻译
- 现有 TTS 脚本负责配音

### 4.3 成本策略

- 不允许对长视频默认自动切换到更便宜模型。
- 只有用户显式启用“成本优先模式”时，才允许切换模型。
- 切换后的 provider/model 选择必须持久化，保证恢复执行可重复。

## 5. 错误恢复与可重试性

### 5.1 总原则

- 失败恢复必须以“最小失败单元”为目标。
- 不允许因为单个 chunk 翻译失败而全量重跑整个 Phase 4。
- 不允许为了重试而删除无关的成功产物。

### 5.2 错误文件

每个阶段脚本失败时应写：

- `temp/<phase>_error.json`

至少包含：

- `script`
- `phase`
- `error`
- `timestamp`

校验失败时应写：

- `temp/validation_errors.json`

### 5.3 重试规则

- 单 chunk 翻译失败：只将对应 chunk 标记为 `failed`，重跑时只调度失败 chunk。
- ASR 失败：可只重跑 `phase_4_asr`，不必重新抽音频。
- 校验失败：必须阻止进入 align/export 或后续 phase。
- 临时网络/IO 错误允许有限次数重试，但最终失败必须落盘，不得静默吞掉。

## 6. 翻译一致性与质量要求

- 术语表通过 `temp/glossary.json` 注入，并在 chunk_build 时合并进各 chunk 的 `glossary_terms`。
- 翻译 prompt 允许带全局上下文，例如标题、简介、前序 chunk 尾句，用于减少术语漂移。
- 时间轴在 ASR、normalize、chunk、align、export 任意步骤都不能丢失。
- 对齐阶段必须以 `segment_ids` 为主键恢复字幕段，不允许仅靠文本模糊匹配。

## 7. Bilibili 发布标准

### 7.1 元数据生成

- 标题：生成 2-3 个适合 B 站的候选标题
- 简介：包含原视频来源、翻译说明、SEO 关键词
- 标签：生成 5-10 个相关标签

### 7.2 发布逻辑

- 登录依赖本地浏览器现有 B 站 Session
- 正式发布使用 `agent-browser` 进行浏览器自动化
- 需要支持 `draft` 和 `formal` 两种模式
- 缺少 `final/final_video.mp4` 时必须明确阻塞，不能静默继续
- 分区选择应支持按视频内容做自动匹配

### 7.3 发布产物

成功后写入：

- `final/publish_result.json`

至少包含：

- `status`
- `video_id`
- `mode`
- `title`
- `description`
- `tags`
- `bilibili_url` 或 `draft_id`

## 8. 视觉、音频与环境标准

- 字幕主输出为 `.ass`
- 支持双语和仅中文两种布局
- Phase 7 只消费 canonical 字幕产物，不重新推断字幕来源
- 中文字幕配音模式下，中文配音完全替换原音
- 运行环境基线：macOS（Mac mini M4）

## 9. 测试与验收

至少覆盖以下场景：

- 官方字幕路径可跳过 ASR，并输出正确 `subtitle_manifest.json`
- 无字幕路径可生成 `source_audio.wav`、`asr_segments.json`、`source_segments.json`
- 单个 chunk 翻译失败后仅重跑该 chunk
- 校验器能拦截缺块、时间轴漂移、疑似未翻译文本
- 双语和仅中文导出时间轴一致
- 中断恢复时已完成 chunk 不重复翻译
- Phase 7 能消费 canonical 产物合成最终视频
- Phase 9 在缺少最终视频时明确阻塞
- JSON schema 能校验所有 canonical artifacts

## 10. 当前范围外能力

以下能力当前不纳入本期实现：

- 多语言目标字幕同时输出
- 动态切换 ASR provider
- 人工审核 UI / workflow
- 跨视频共享术语库
- `phase_runner.py` 之外的第二套入口

---

_本文档为 YouTube 视频翻译 Skill 的 V4 规格说明。后续实现、评审和文档更新应以本版本为准。_
