# YouTube Video Translator Skill

专业级 YouTube 视频翻译工具，使用 edge-tts 生成免费高质量配音。

## 安装

```bash
# 克隆到本地 skills 目录
git clone https://github.com/dfang/youtube-video-translator.git ~/.openclaw/skills/youtube-video-translator

# 安装 Python 依赖
pip3 install -r requirements.txt

# 无需 API 密钥 - edge-tts 完全免费使用
```

## 快速开始

### 1. 安装依赖

```bash
pip3 install -r requirements.txt
```

确保已安装 `edge-tts`：
```bash
pip3 install edge-tts
```

### 2. 使用技能

在 OpenClaw 聊天中：
```
/yt-translate https://www.youtube.com/watch?v=VIDEO_ID
```

或直接发送链接并说"翻译这个视频"。

## 输出示例

```
✅ 视频翻译完成！

最终文件：VIDEO_TITLE.zh-CN.final.mp4 (63.0MB)
- 🎬 1280x556 视频
- 🎙️ 中文配音（edge-tts）
- 📝 硬烧字幕（中文字幕或中英文双语）
- ⏱️ 时长 19:15

中间文件已保留在工作区。
使用 --cleanup 参数可清理中间文件。
```

**注意**：最终视频已硬烧入字幕，可在 QuickTime Player 或任何 MP4 播放器直接显示字幕，无需外部字幕文件。

## 高级用法

### Telegram 进度回报（默认开启）
`translate.sh` 默认会输出机器可解析的进度事件（适合 Telegram 机器人）：

```text
TG_PROGRESS|<step>|<total>|<status>|<description>
```

如需关闭，显式设置：
```bash
TELEGRAM_PROGRESS=0
```

### 清理中间文件
```
/yt-translate <URL> --cleanup
```

### 指定目标语言
```
/yt-translate <URL> --lang ja  # 翻译成日语
```

### 选择字幕类型
```
# 仅中文字幕（默认）
/yt-translate <URL> --subtitles chinese

# 中英文双语字幕
/yt-translate <URL> --subtitles bilingual
```

### 选择字幕来源
```
# 下载 YouTube 英文字幕（默认，无逐词高亮）
/yt-translate <URL> --subtitle-source download

# 使用 Whisper 重新生成字幕（质量更高，时间轴干净）
# 默认使用 large-v3-turbo 模型 + 医学词汇表
/yt-translate <URL> --subtitle-source whisper

# 使用 faster-whisper + whisperx 对齐（最佳质量，单词级精度）
# 默认使用 large-v3-turbo 模型 + 医学词汇表
/yt-translate <URL> --subtitle-source whisperx
```

Whisper 模式需要先安装：
```bash
# 标准 Whisper（较慢）
pip install openai-whisper

# Faster-Whisper（推荐，速度更快）
pip install faster-whisper

# WhisperX（最佳质量，单词级对齐）
pip install faster-whisper whisperx
```

### 组合多个参数
```
/yt-translate <URL> --subtitles bilingual --cleanup --lang zh-CN
```

### 提高转录准确性（针对专业术语）

**默认配置**：whisper/whisperx 模式默认使用 `large-v3-turbo` 模型 + 医学词汇表，无需额外参数。

当视频包含其他领域专业术语时，可以自定义：

```
# 使用更大的 Whisper 模型（精度更高，速度更慢）
/yt-translate <URL> --subtitle-source whisper --whisper-model large-v3

# 使用内置科技词汇表（而非默认的医学词汇表）
/yt-translate <URL> --subtitle-source whisper --vocab tech

# 使用自定义词汇文件（每行一个术语）
/yt-translate <URL> --subtitle-source whisper --vocab-file my-terms.txt

# 关闭词汇表（不使用任何术语提示）
/yt-translate <URL> --subtitle-source whisper --vocab ""
```

**Whisper 模型选项**：
- `tiny` - 最快，精度最低
- `base` - 快速，一般精度
- `small` - 中等速度，较好精度
- `medium` - 默认，平衡速度与精度
- `large-v3` - 最慢，精度最高（推荐用于专业内容）
- `large-v3-turbo` - large-v3 的加速版本

**内置词汇表**：
- `medical` - 医学术语（ARDS, COVID-19, ICU, ventilator, 等）
- `tech` - 科技术语（API, Kubernetes, Docker, JavaScript, 等）

**自定义词汇文件格式** (my-terms.txt)：
```
# 每行一个术语
ARDS
acute respiratory distress syndrome
COVID-19
SARS-CoV-2
```

转录完成后会显示预览，可按 `e` 手动编辑校正确认后再继续翻译。

## 技术细节

### edge-tts TTS 生成
1. 解析 SRT 字幕文件获取时间轴和文本
2. 按目标语言选择预设语音（如 zh-CN-XiaoxiaoNeural）
3. 调用 edge-tts CLI 逐句生成音频片段
4. 生成 voice-map.json 记录片段映射
5. 使用 ffmpeg 合并所有音频片段

### 字幕处理
- 字幕来源选项：
  - `download`（默认）：下载 YouTube 英文字幕，使用 yt-dlp 下载原始字幕（无逐词高亮）
  - `whisper`：使用 Whisper/faster-whisper 本地转录（无高亮，时间轴干净，质量更高）
  - `whisperx`：使用 faster-whisper + whisperx 对齐（单词级精度，最佳质量）
- 自动检测并转换字幕格式（VTT → SRT）
- 长字幕自动切分（每段<4000 字符）
- 大模型 API 翻译（Anthropic 兼容接口，支持阿里云 Coding Plan）
- 严格禁用 Google Translate fallback

### MPS 加速
Mac M 系列芯片自动启用 Metal Performance Shaders：
- 音频分析（librosa）
- 本地转录（如使用 Whisper）

### 大模型翻译配置（必需）
英文字幕翻译必须使用大模型，不会回退到 Google Translate。请在 `.env` 配置：

```bash
# 阿里云 Coding Plan 示例
ANTHROPIC_AUTH_TOKEN="sk-sp-xxx"
ANTHROPIC_BASE_URL="https://coding.dashscope.aliyuncs.com/apps/anthropic"
ANTHROPIC_MODEL="qwen3-coder-plus"
```

## 故障排除

### 下载失败
检查网络连接，或尝试添加 `--cookies-from-browser=chrome`。

### 配音生成失败
确保已安装 edge-tts：`pip3 install edge-tts`

## 文件结构

```
youtube-video-translator/
├── SKILL.md              # 技能定义
├── README.md             # 本文档
├── requirements.txt      # Python 依赖
├── scripts/
│   ├── translate.sh      # 主入口
│   ├── download.sh       # 下载模块
│   ├── transcribe.sh     # 转录/翻译
│   ├── dub.sh            # 配音模块
│   └── merge.sh          # 合成模块
└── config/
    └── default.json      # 默认配置
```

## License

MIT License
