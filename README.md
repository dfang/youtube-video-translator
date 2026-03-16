# YouTube Video Translator Skill

专业级 YouTube 视频翻译工具，使用 edge-tts 生成免费高质量配音。

## 安装

```bash
# 克隆或复制技能到 OpenClaw 技能目录
# 技能路径：~/.openclaw/workspace/skills/youtube-video-translator

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
/yt-translate <URL> --subtitle-source whisper
```

Whisper 模式需要先安装：
```bash
# 标准 Whisper（较慢）
pip install openai-whisper

# Faster-Whisper（推荐，速度更快）
pip install faster-whisper
```

### 组合多个参数
```
/yt-translate <URL> --subtitles bilingual --cleanup --lang zh-CN
```

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
- 自动检测并转换字幕格式（VTT → SRT）
- 长字幕自动切分（每段<4000 字符）
- Google Translate API 翻译

### MPS 加速
Mac M 系列芯片自动启用 Metal Performance Shaders：
- 音频分析（librosa）
- 本地转录（如使用 Whisper）

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
