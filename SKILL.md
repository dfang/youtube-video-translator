# YouTube Video Translator / YouTube 视频翻译

专业级 YouTube 视频翻译工具，自动下载视频、翻译字幕、克隆声音配音，输出中文配音视频。

## 触发条件

当用户提到以下内容时自动触发：

- `/yt-translate` 命令后跟 YouTube 链接
- "翻译这个视频" + YouTube 链接
- "youtube 翻译"、"视频翻译"、"yt 翻译"
- "把 youtube 视频翻译成中文"
- 直接发送 YouTube 链接并提到翻译相关关键词

## 核心流程

### 1. 下载模块 (download.sh)

- 使用 `yt-dlp` 下载 YouTube 视频（最高画质 + 最佳音质）
- 自动下载多语言字幕（英文、简体中文）
- 提取音频用于声音克隆
- 支持从 Chrome 浏览器读取 Cookie 以绕过限制

### 2. 字幕处理模块 (transcribe.sh)

- 自动检测并转换字幕格式（VTT → SRT）
- 使用 Google Translate API 逐句翻译字幕
- 保留原字幕时间轴
- 输出双语 SRT 字幕文件

### 3. 配音生成模块 (dub.sh)

- **声音克隆**：使用 ElevenLabs Instant Voice Cloning 克隆原视频人物声音
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

### 🎙️ 声音克隆

- 优先克隆原视频人物声音，保持配音自然度
- 使用 ElevenLabs 多语言模型 (eleven_multilingual_v2)
- 支持使用预设声音库（`--voice-library` 参数）

### ⚡ MPS 加速

- Mac M 系列芯片自动启用 Metal Performance Shaders
- 音频分析和转录获得硬件加速

### 📹 高质量输出

- 保留原始视频画质（1080p/4K）
- AAC 音频编码
- 可选嵌入软字幕

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

### 带参数

```bash
# 清理中间文件
/yt-translate <URL> --cleanup

# 指定目标语言（默认中文）
/yt-translate <URL> --lang ja  # 翻译成日语

# 使用预设声音而非克隆
/yt-translate <URL> --voice-library

# 字幕类型：仅中文（默认）或中英文双语
/yt-translate <URL> --subtitles chinese      # 仅中文字幕（默认）
/yt-translate <URL> --subtitles bilingual    # 中英文双语字幕
```

## 环境变量

| 变量名               | 说明                        |
| -------------------- | --------------------------- |
| `ELEVENLABS_API_KEY` | ElevenLabs API 密钥（必需） |

## 输出文件

默认保留所有中间文件：

| 文件后缀                | 说明                     |
| ----------------------- | ------------------------ |
| `*.original.mp4`        | 原始视频                 |
| `*.en.vtt` / `*.en.srt` | 英文字幕                 |
| `*.zh-CN.srt`           | 中文字幕（仅中文）       |
| `*.en.only.srt`         | 英文字幕（仅英文，双语模式生成） |
| `*.audio.mp3`           | 原音频                   |
| `*.voice-map.json`      | 配音元数据               |
| `*.zh-CN.merged.mp3`    | 合并后的中文配音         |
| `*.zh-CN.final.mp4`     | 最终输出视频（含配音 + 硬烧字幕）   |
| `subtitles.ass`         | ASS 格式字幕（用于硬烧） |

**注意**：最终输出视频 `*.zh-CN.final.mp4` 已硬烧入字幕，可在 QuickTime Player 等任何播放器直接显示字幕。

## 依赖

- `yt-dlp` - YouTube 视频下载
- `ffmpeg` - 视频/音频处理
- Python 3.10+
- ElevenLabs API
- Python 包：`elevenlabs`, `requests`

## 配置参数 (config/default.json)

```json
{
  "elevenlabs": {
    "model": "eleven_multilingual_v2",
    "stability": 0.5,
    "similarity_boost": 0.75,
    "style": 0.0,
    "use_speaker_boost": true
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

## 技术细节

### 声音克隆流程

1. 从原视频提取 1-3 分钟音频片段
2. 发送到 ElevenLabs Instant Voice Cloning API
3. 获取克隆声音的 voice_id
4. 使用该 voice_id 逐句生成 TTS

### 字幕翻译

- 使用 Google Translate 免费 API
- 自动检测源语言
- 逐句翻译保留时间轴
- 速率限制避免请求过快

### 视频合成

- 视频流直接复制（无重编码）
- 音频重新编码为 AAC
- 可选使用 ffmpeg 烧录字幕
