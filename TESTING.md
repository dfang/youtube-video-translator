# YouTube Video Translator - Test & Examples

## 测试用例

### 基础测试
```bash
cd /Users/fang/.openclaw/workspace/skills/youtube-video-translator
export ELEVENLABS_API_KEY="your_key"

# 短视频测试（Shorts）
./scripts/translate.sh "https://www.youtube.com/shorts/wOHC5tgsvlA"

# 长视频测试
./scripts/translate.sh "https://www.youtube.com/watch?v=VIDEO_ID"

# 带清理参数
./scripts/translate.sh "https://www.youtube.com/watch?v=VIDEO_ID" --cleanup

# 指定语言
./scripts/translate.sh "https://www.youtube.com/watch?v=VIDEO_ID" --lang ja
```

## OpenClaw 集成

在 OpenClaw 中使用时，技能会自动检测以下触发条件：
- `/yt-translate <URL>`
- "翻译这个视频" + URL
- "youtube 翻译" + URL

## 预期输出

```
🎬 YouTube 视频翻译工具
━━━━━━━━━━━━━━━━━━━━━━
📺 视频链接：https://www.youtube.com/shorts/wOHC5tgsvlA
🌐 目标语言：zh-CN
🎙️ 声音克隆：克隆原声

📥 步骤 1/5: 下载视频和字幕...
  获取视频信息...
  视频标题：Sleepy Trump vs Sleepy Joe
  保存名称：Sleepy Trump vs Sleepy Joe
  下载视频...
  下载字幕...
  提取音频...
✅ 下载完成

📝 步骤 2/5: 处理字幕...
  找到字幕文件：Sleepy Trump vs Sleepy Joe.en.vtt
  翻译字幕为 zh-CN...
  共 5 条字幕
  翻译完成！
  已保存：Sleepy Trump vs Sleepy Joe.zh-CN.srt
✅ 字幕处理完成

🎙️ 步骤 3/5: 生成中文配音...
  字幕文件：Sleepy Trump vs Sleepy Joe.zh-CN.srt
  参考音频：Sleepy Trump vs Sleepy Joe.audio.mp3
  调用 ElevenLabs 生成配音...
    正在克隆声音...
    声音克隆成功：voice_id_xxx
  共 5 条字幕
  配音生成完成！
  已保存元数据：Sleepy Trump vs Sleepy Joe.voice-map.json
✅ 配音生成完成

🎬 步骤 4/5: 合成视频...
  视频文件：Sleepy Trump vs Sleepy Joe.original.mp4
  配音元数据：Sleepy Trump vs Sleepy Joe.voice-map.json
  合并音频并合成视频...
    合并音频片段...
    合成最终视频...
    嵌入中文字幕...
  最终文件：Sleepy Trump vs Sleepy Joe.zh-CN.final.mp4
  分辨率：1080x1920
  时长：23.4 秒
  大小：5.6MB
✅ 视频合成完成

💾 中间文件已保留在工作区
✅ 翻译完成！
```

## 故障排除

### 问题：ElevenLabs API 限流
**解决：** 等待 1 分钟或减少并发请求

### 问题：下载失败
**解决：** 
```bash
# 尝试不使用浏览器 cookies
yt-dlp -f "best" "URL"

# 或使用代理
yt-dlp --proxy "http://127.0.0.1:7890" "URL"
```

### 问题：翻译速度慢
**解决：** Google Translate 有速率限制，已内置 0.5 秒延迟

### 问题：声音克隆效果差
**解决：** 
- 确保原视频音频清晰
- 背景音乐不要太吵
- 尝试使用 `--voice-library` 使用预设声音
