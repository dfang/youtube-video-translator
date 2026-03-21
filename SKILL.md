---
name: youtube-video-translator
description: Professional YouTube video translator - downloads video, translates subtitles with LLM, clones voice for dubbing, outputs Chinese dubbed video. Triggers on "翻译视频" + YouTube URL.
metadata: {"openclaw":{"emoji":"🎬","requires":{"bins":["yt-dlp","ffmpeg","bash"],"env":["ANTHROPIC_AUTH_TOKEN","ELEVENLABS_API_KEY"]},"primaryEnv":"ANTHROPIC_AUTH_TOKEN"}}
---

# YouTube Video Translator / YouTube 视频翻译

专业级 YouTube 视频翻译工具，自动下载视频、翻译字幕、克隆声音配音，输出中文配音视频。

**⚠️ 优先级规则：** 当用户发送 YouTube 链接 + 翻译/字幕/配音相关关键词时，**必须使用此技能**，而不是 summarize 或其他工具。

## 硬性约束（必须遵守）

- 英文字幕翻译 **必须使用大模型 API**（Anthropic 兼容接口，如 Anthropic 官方或阿里云 Coding Plan）。
- **严禁使用 Google Translate**（包括任何 fallback / 降级路径）。
- 若未配置大模型鉴权（如 `ANTHROPIC_AUTH_TOKEN`）或模型不可用，必须直接报错并停止，不输出半成品翻译结果。

## 触发条件

当用户提到以下内容时**立即触发此技能**（优先级高于 summarize）：

- `/yt-translate` 命令后跟 YouTube 链接
- "翻译视频" / "翻译这个视频" + YouTube 链接（**核心触发**）
- "youtube 翻译"、"yt 翻译"、"视频翻译" + YouTube 链接
- "把 youtube 视频翻译成中文"
- 直接发送 YouTube 链接并提到"翻译"、"字幕"、"配音"等关键词
- "translate this video" / "youtube translate" + URL

**注意：** 当用户发送 YouTube 链接 + 翻译相关关键词时，**必须使用此技能**，而不是 summarize。

## 可用参数

| 参数 | 选项 | 默认值 | 说明 |
|------|------|--------|------|
| `--audio-mode` | `original` \| `dub` | `dub` | 音频模式：保留原音或生成配音 |
| `--subtitle-source` | `download` \| `whisper` \| `whisperx` | `download` | 字幕来源 |
| `--tts-engine` | `edge-tts` \| `piper-tts` | `edge-tts` | TTS 引擎 |
| `--subtitles` | `chinese` \| `bilingual` | `chinese` | 字幕类型 |
| `--cleanup` | - | - | 完成后清理中间文件 |
| `--lang` | 语言代码 | `zh-CN` | 目标语言 |

## OpenClaw 执行指令

当用户回复选择后，执行对应的命令：

```
用户回复 → 解析 → 执行命令
```

### 命令映射表

| 用户输入 | 解析结果 | 执行命令 |
|---------|---------|---------|
| "1" | mode=fast, sub=cn | `bash scripts/translate.sh "{URL}"` |
| "1B" 或 "1 双语" | mode=fast, sub=bi | `bash scripts/translate.sh "{URL}" --subtitles bilingual` |
| "2" | mode=whisperx, sub=cn | `bash scripts/translate.sh "{URL}" --subtitle-source whisperx` |
| "2B" 或 "2 双语" | mode=whisperx, sub=bi | `bash scripts/translate.sh "{URL}" --subtitle-source whisperx --subtitles bilingual` |
| "3" | mode=original, sub=cn | `bash scripts/translate.sh "{URL}" --audio-mode original` |
| "3B" 或 "3 双语" | mode=original, sub=bi | `bash scripts/translate.sh "{URL}" --audio-mode original --subtitles bilingual` |
| "4" | mode=local, sub=cn | `bash scripts/translate.sh "{URL}" --audio-mode original --subtitle-source whisperx` |
| "4B" 或 "4 双语" | mode=local, sub=bi | `bash scripts/translate.sh "{URL}" --audio-mode original --subtitle-source whisperx --subtitles bilingual` |

### 执行命令格式

所有命令统一使用以下格式（在技能目录内执行）：

```bash
bash scripts/translate.sh "{VIDEO_URL}" [OPTIONS]
```

目录无关示例：
```bash
cd /path/to/.openclaw/skills/youtube-video-translator
bash scripts/translate.sh "https://youtube.com/watch?v=XXX"
```

### 选项组合速查

| 模式 | 对应参数 |
|------|---------|
| 快速模式 | （无参数，使用默认） |
| 高质量转录 | `--subtitle-source whisperx` |
| 仅原音 | `--audio-mode original` |
| 完整本地 | `--audio-mode original --subtitle-source whisperx` |
| 双语字幕 | `--subtitles bilingual` |

---

## 执行流程

### Claude 应该先询问的情况：

当用户**只提供 URL 而没有其他参数**时，先输出以下询问：

```
🎬 YouTube 视频翻译选项

📺 视频链接：{URL}

请选择处理模式（回复数字或直接执行）：

1️⃣ 快速模式（推荐）
   - 下载 YouTube 字幕 + 中文配音
   - 速度快，适合娱乐视频

2️⃣ 高质量转录
   - WhisperX 本地转录 + 中文配音
   - 质量更高，适合学术/专业视频

3️⃣ 仅原音模式
   - 下载 YouTube 字幕 + 保留原音 + 中文字幕
   - 适合想听原声的视频

4️⃣ 完整本地模式
   - WhisperX 转录 + 保留原音 + 中文字幕
   - 完全本地处理，最高质量

字幕类型（可一并选择）：
- C: 仅中文字幕（默认）
- B: 中英文双语字幕

示例回复：
- "1" 或 "快速模式" → 使用快速模式 + 仅中文
- "2B" 或 "2 双语" → 使用高质量转录 + 双语字幕
- "3" → 仅原音模式
- 直接说参数如 "--audio-mode original" → 使用指定参数
```

等待用户回复后，根据选择执行对应命令：

| 用户选择 | 执行命令 |
|---------|---------|
| 1 或快速模式 | `bash scripts/translate.sh {URL}` |
| 2 或高质量 | `bash scripts/translate.sh {URL} --subtitle-source whisperx` |
| 3 或仅原音 | `bash scripts/translate.sh {URL} --audio-mode original` |
| 4 或完整本地 | `bash scripts/translate.sh {URL} --audio-mode original --subtitle-source whisperx` |
| +B 或双语 | 添加 `--subtitles bilingual` |

### 直接执行的情况：

当用户命令中包含以下任一参数时，**直接执行，不要询问**：
- `--audio-mode`
- `--subtitle-source`
- `--tts-engine`
- `--subtitles`

## 核心流程

### 1. 下载模块 (download.sh)

- 使用 `yt-dlp` 下载 YouTube 视频（最高画质 + 最佳音质）
- 自动下载多语言字幕（英文、简体中文）
- 提取音频用于声音克隆
- 支持从 Chrome 浏览器读取 Cookie 以绕过限制

### 2. 字幕处理模块 (transcribe.sh)

- 自动检测并转换字幕格式（VTT → SRT）
- 使用大模型 API 进行批量字幕翻译（支持阿里云 Coding Plan Anthropic 兼容网关）
- 保留原字幕时间轴
- 输出双语 SRT 字幕文件
- 检测英文残留并自动补翻（仅大模型路径，不允许 Google fallback）
- **字幕来源选项**：
  - `download`（默认）：下载 YouTube 英文字幕，使用 yt-dlp 下载原始字幕（无逐词高亮）
  - `whisper`：使用 Whisper/faster-whisper 本地转录（无高亮，时间轴干净，质量更高）
  - `whisperx`：faster-whisper + whisperx 单词级对齐（最佳质量）

### 3. 配音生成模块 (dub.sh)

- **edge-tts TTS**: 使用 Microsoft Edge TTS 生成高质量配音
- **piper-tts TTS**: 本地离线 TTS，需要安装和下载模型
- **分段生成**：按字幕时间轴逐句生成 TTS 音频
- **语速匹配**：自动匹配原视频语速和停顿
- **元数据记录**：生成 voice-map.json 记录每个音频片段的时间信息

### 4. 视频合成模块 (merge.sh)

- 合并所有 TTS 音频片段
- 将中文配音与原始视频合成
- 自动嵌入中文字幕（可选）
- 输出最终 MP4 视频文件

### 5. 清理模块 (cleanup.sh)

- 可选清理中间文件
- 保留最终输出视频和字幕

## 特色功能

### 🎙️ TTS 引擎

**edge-tts**（默认）：
- 免费无需 API 密钥
- 无速率限制，快速生成
- 支持 30+ 语言的高质量语音
- 在线服务，需要网络

**piper-tts**（可选）：
- 本地离线运行
- 需要安装 piper 和下载模型
- 隐私安全

### ⚡ MPS 加速

- Mac M 系列芯片自动启用 Metal Performance Shaders
- 音频分析和转录获得硬件加速

### 📹 高质量输出

- 保留原始视频画质（1080p/4K）
- AAC 音频编码
- HandBrake 硬烧字幕

### 🛡️ 容错策略

- 单步失败时尝试降级方案
- 字幕下载失败时提示但继续
- 声音克隆失败时切换预设声音
- 输出部分可用结果

## 使用方法

### 基本用法

```bash
/yt-translate https://www.youtube.com/watch?v=VIDEO_ID
```

### 常用组合

```bash
# 保留原音 + 高质量转录（推荐用于学术视频）
/yt-translate <URL> --audio-mode original --subtitle-source whisperx

# 快速翻译（默认设置）
/yt-translate <URL>

# 本地 TTS + 双语字幕
/yt-translate <URL> --tts-engine piper-tts --subtitles bilingual

# 清理中间文件
/yt-translate <URL> --cleanup
```

## 环境变量

无需 API 密钥，edge-tts 完全免费使用。

如需使用 ElevenLabs 声音克隆，设置：
```bash
export ELEVENLABS_API_KEY="your_key"
```

## 输出文件

默认保留所有中间文件：

| 文件后缀                | 说明                     |
| ----------------------- | ------------------------ |
| `*.original.mp4`        | 原始视频                 |
| `*.en.vtt` / `*.en.srt` | 英文字幕                 |
| `*.zh-CN.srt`           | 中文字幕（仅中文）       |
| `*.en.only.srt`         | 英文字幕（仅英文，双语模式） |
| `*.audio.mp3`           | 原音频                   |
| `*.voice-map.json`      | 配音元数据               |
| `*.zh-CN.merged.mp3`    | 合并后的中文配音         |
| `*.zh-CN.final.mp4`     | 最终输出视频（含配音 + 硬烧字幕） |
| `subtitles.ass`         | ASS 格式字幕（用于硬烧） |

**注意**：最终输出视频 `*.zh-CN.final.mp4` 已硬烧入字幕，可在 QuickTime Player 等任何播放器直接显示字幕。

## 依赖

- `yt-dlp` - YouTube 视频下载
- `ffmpeg` - 视频/音频处理
- `HandBrakeCLI` - 硬烧字幕（可选）
- Python 3.10+
- Python 包：`edge-tts`, `requests`

可选依赖：
- `faster-whisper` - 更快的 Whisper 实现
- `whisperx` - 单词级对齐
- `piper-tts` - 本地 TTS

## 配置参数 (config/default.json)

```json
{
  "edge-tts": {
    "default_voice": "zh-CN-XiaoxiaoNeural",
    "voice_mapping": {
      "zh-CN": "zh-CN-XiaoxiaoNeural",
      "zh-HK": "zh-HK-HiuMaanNeural",
      "zh-TW": "zh-TW-HsiaoChenNeural",
      "ja": "ja-JP-NanamiNeural",
      "ko": "ko-KR-SunHiNeural",
      "en": "en-US-JennyNeural",
      "es": "es-ES-ElviraNeural",
      "fr": "fr-FR-DeniseNeural",
      "de": "de-DE-KatjaNeural"
    }
  },
  "translation": {
    "target_language": "zh-CN",
    "subtitle_max_chars": 4000
  },
  "download": {
    "video_format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
    "subtitle_languages": ["en", "zh-Hans", "zh-Hant"],
    "cookies_from_browser": "chrome"
  }
}
```

## 错误处理

采用容错策略（策略 B）：

- 单步失败时尝试降级方案
- 输出部分可用结果
- 详细错误日志便于调试
