# YouTube Video Translator Skill

专业级 YouTube 视频翻译工具，专为 Mac Mini M4 优化。

## 安装

```bash
# 克隆或复制技能到 OpenClaw 技能目录
# 技能路径：~/.openclaw/workspace/skills/youtube-video-translator

# 安装 Python 依赖
pip3 install -r requirements.txt

# 设置环境变量
export ELEVENLABS_API_KEY="your_api_key_here"
```

## 快速开始

### 1. 配置 API Key

在终端执行：
```bash
export ELEVENLABS_API_KEY="你的 ElevenLabs API 密钥"
```

或添加到 `~/.zshrc`：
```bash
echo 'export ELEVENLABS_API_KEY="your_key"' >> ~/.zshrc
source ~/.zshrc
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

最终文件：VIDEO_TITLE.zh-CN.final.mp4 (15.2MB)
- 🎬 1920x1080 视频
- 🎙️ 中文配音（克隆原声）
- ⏱️ 时长 3:24

中间文件已保留在工作区。
使用 --cleanup 参数可清理中间文件。
```

## 高级用法

### 清理中间文件
```
/yt-translate <URL> --cleanup
```

### 使用预设声音（不克隆）
```
/yt-translate <URL> --voice-library
```

### 指定目标语言
```
/yt-translate <URL> --lang ja  # 翻译成日语
```

## 技术细节

### 声音克隆流程
1. 从原视频提取音频片段（1-3 分钟最佳）
2. 发送到 ElevenLabs Instant Voice Cloning
3. 使用克隆的声音进行 TTS
4. 自动匹配原音频语速和停顿

### 字幕处理
- 优先下载 YouTube 自动/手动字幕
- 无字幕时使用 Whisper 自动转录
- 长字幕自动切分（每段<4000 字符）
- Google Translate API 翻译

### MPS 加速
Mac M 系列芯片自动启用 Metal Performance Shaders：
- 音频分析（librosa）
- 本地转录（如使用 Whisper）

## 故障排除

### API 限流
ElevenLabs 有字符限制，长视频会自动切分处理。

### 下载失败
检查网络连接，或尝试添加 `--cookies-from-browser=chrome`。

### 声音克隆效果不佳
确保原视频音频清晰，无明显背景音乐干扰。

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
