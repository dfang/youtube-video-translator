# YouTube 视频翻译 Skill 需求规格说明书 (YouTube Translator Skill Requirements) - V3

本文件整理了关于“YouTube 视频翻译”Skill 的深度讨论、模块化架构及 Bilibili 自动化发布逻辑。

## 1. 核心架构：模块化、断点续传与发布 (Architecture & Publishing)

该 Skill 采用 **状态驱动 (State-driven)** 模式。除原有的 5 个处理阶段外，新增“自动发布”阶段：

- **检查点逻辑**:
  1. 若无原始视频 -> `downloader`。
  2. 若无翻译字幕 -> `subtitle_manager` (WhisperX + LLM)。
  3. 若无配音音频 -> `voiceover_engine` (TTS)。
  4. 若无最终成品 -> `video_composer` (FFmpeg)。
  5. **发布逻辑 (NEW)** -> `bilibili_publisher` (Browser Automation)。

## 2. 子模块职责定义 (Sub-module Responsibilities)

- **`downloader`**: 下载原始视频及元数据。
- **`subtitle_manager`**: 转录 (WhisperX) 并由 LLM 翻译生成 `.ass` 字幕。
- **`voiceover_engine`**: 生成中文配音音频。
- **`video_composer`**: 合成最终视频。
- **`cleaner`**: 根据需求清理中间文件。
- **`bilibili_publisher` (NEW)**:
  - **交互模式**: 模拟真实用户通过 **浏览器 (agent-browser)** 进行操作。
  - **功能**: 上传视频、填写元数据、选择分区。
  - **状态**: 支持“发布”或“存草稿”。

## 3. Bilibili 发布标准 (Bilibili Publishing Standards)

- **元数据生成 (LLM Optimized)**:
  - **标题**: 自动生成 2-3 个吸引人的 B站标题供选择（或直接使用最佳标题）。
  - **简介**: 自动生成包含原视频来源、翻译说明及 SEO 关键词的详细简介。
  - **标签 (Tags)**: 自动生成 5-10 个相关性强的标签。
- **发布逻辑**:
  - **登录**: 依赖本地浏览器已登录的 B站 Session。
  - **上传**: 使用 `agent-browser` 操作 B站创作中心上传组件。
  - **分区自适应**: 根据视频内容自动匹配 B站分区（如：科技 -> 机械、医学 -> 校园）。
  - **安全**: 模拟真实点击和延迟，避免被判定为机器人。

## 4. 视觉、音频与环境标准 (Environment & Standards)

- **字幕样式**: `.ass` 格式，英文在上中文在下，16号白色。
- **音频处理**: 中文配音完全替换原音。
- **运行环境**: macOS (Mac mini M4)。

## 5. 待办事项 (Next Steps)

- [ ] 编写基于浏览器自动化的发布指令脚本。
- [ ] 设计 Bilibili 分区自动选择逻辑。
- [ ] 为“发布/草稿”功能编写针对性的测试用例。

---

_本文档是 YouTube 视频翻译 Skill 的 V3 施工指南，所有实现应严格遵循上述标准。_
