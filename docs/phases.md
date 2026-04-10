共有 12 个 phase（Phase 0 到 Phase 11）：

| Phase | 名称 | 类型 |
|-------|------|------|
| 0 | 环境验证 | 脚本 |
| 1 | 收集意图（交互式） | 交互 |
| 2 | 初始化设置 | 脚本 |
| 3 | 元数据 + 字幕发现 + 视频下载 | 脚本 |
| 4 | 字幕获取 → 分块翻译 → 对齐 → 导出 | 脚本 |
| 5 | 语音合成（Voiceover） | 脚本 |
| 6 | 合成最终视频 | 脚本 |
| 7 | 封面生成 | **子代理** |
| 8 | 描述生成器 | **子代理** |
| 9 | 上传预览 | **子代理** |
| 10 | B站发布 | 脚本 |
| 11 | 清理 | 脚本 |

## Phase 1 意图选项

| 字段 | 选项 | 默认值 |
|------|------|--------|
| `audio_mode` | `original` / `voiceover` | `original` |
| `subtitle_mode` | `auto` / `official_only` / `transcribe` | `auto` |
| `subtitle_layout` | `bilingual` / `chinese_only` | `bilingual` |
| `publish` | `true` / `false` | `false` |
| `cleanup` | `true` / `false` | `false` |

**隐式同意**: 如果用户只说"开始"/"start"/"go"等，未回答具体问题，直接使用默认值并设置 `confirmed: true`。

## Phase 4 完整流程

Step 1：字幕获取（两条路径）

- 官方字幕路径（`subtitle_mode=auto/official_only`）：用 `caption_fetch.py` 通过 yt-dlp 下载官方字幕 → `temp/source_segments.json`
- ASR 转录路径（`subtitle_mode=transcribe` 或无官方字幕时）：用 `audio_extract.py` 提取音频 → WhisperX 转录 → `asr_normalize.py` 规范化 → `temp/source_segments.json`

Step 2：分块（chunk_build）

将 `source_segments.json` 按时间边界拆分成多个 chunk → `temp/chunks.json`（供并行翻译用）

Step 3：并行翻译（translate_scheduler）

启动多个子 agent（默认 4 个并发），每个子 agent 翻译一个 chunk，翻译结果写回 `chunks.json`

Step 4：校验（validator）

所有 chunk 翻译完成后统一校验：检查是否有缺失 ID、时间重叠、未翻译文本 → 失败则报错并重译对应 chunk

Step 5：对齐（align）

将翻译后的 chunk 与源字幕段对齐 → `temp/subtitle_manifest.json`

Step 6：导出（export）

- `layout=bilingual` → 导出 `temp/bilingual.ass`（中文在上，原文在下）
- `layout=chinese_only` → 导出 `temp/zh_only.ass`

## Phase 7/8/9 子代理

- **Phase 7 封面生成** (`agents/cover.md`)：生成 5 个标题/副标题候选，用户选编号后渲染 `final/cover_final.jpg`
- **Phase 8 描述生成** (`agents/description.md`)：生成 Bilibili 可用的纯中文描述，写入 `final/description.txt`
- **Phase 9 上传预览** (`agents/uploader.md`)：上传视频至 Filebin，生成 `final/preview.txt`

## Phase 10 发布模式

- `draft` — 仅生成 `final/publish_result.json`，不执行 Bilibili 上传
- `formal` — 通过 `agent-browser` skill UI 自动化完成 Bilibili 正式发布

## 最终产物

| Phase | 输出 |
|-------|------|
| 3 | `temp/metadata.json`, `temp/caption_plan.json`, `temp/video.mp4` |
| 4 | `temp/subtitle_manifest.json`, `temp/bilingual.ass` / `temp/zh_only.ass` |
| 5 | `temp/zh_voiceover.mp3` |
| 6 | `final/final_video.mp4` |
| 7 | `final/cover_final.jpg` |
| 8 | `final/description.txt` |
| 9 | `final/preview.txt` |
| 10 | `final/publish_result.json` |
