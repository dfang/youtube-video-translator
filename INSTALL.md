# 安装指南

## 快速安装

### 1. 环境变量
```bash
# 添加到 ~/.zshrc
echo 'export ELEVENLABS_API_KEY="你的 API 密钥"' >> ~/.zshrc
source ~/.zshrc
```

### 2. 安装依赖
```bash
# 安装系统工具
brew install yt-dlp ffmpeg

# 安装 Python 依赖
pip3 install -r /Users/fang/.openclaw/workspace/skills/youtube-video-translator/requirements.txt
```

### 3. 创建软链接（可选）
```bash
# 全局使用 yt-translate 命令
ln -s /Users/fang/.openclaw/workspace/skills/youtube-video-translator/scripts/yt-translate /usr/local/bin/yt-translate
```

### 4. 测试
```bash
# 方法 1：直接运行脚本
/Users/fang/.openclaw/workspace/skills/youtube-video-translator/scripts/translate.sh "https://www.youtube.com/shorts/wOHC5tgsvlA"

# 方法 2：使用全局命令（如果创建了软链接）
yt-translate "https://www.youtube.com/shorts/wOHC5tgsvlA"

# 方法 3：在 OpenClaw 中使用
/yt-translate https://www.youtube.com/shorts/wOHC5tgsvlA
```

## 获取 ElevenLabs API Key

1. 访问 https://elevenlabs.io
2. 注册/登录账号
3. 进入 Profile → API Keys
4. 生成新 API Key
5. 复制到环境变量

## 验证安装

```bash
# 检查依赖
yt-dlp --version
ffmpeg -version
python3 --version

# 检查 API Key
echo $ELEVENLABS_API_KEY

# 测试翻译
yt-translate "https://www.youtube.com/shorts/wOHC5tgsvlA" --cleanup
```

## 常见问题

### Q: 没有 brew 怎么办？
A: 安装 Homebrew: https://brew.sh

### Q: Python 依赖安装失败？
A: 尝试使用 `pip3 install --break-system-packages -r requirements.txt`

### Q: 如何在 OpenClaw 中自动触发？
A: 技能已配置触发词，直接说"翻译这个视频" + 链接即可
