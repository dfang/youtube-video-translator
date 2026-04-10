# YouTube Video Translator

YouTube 视频本地化翻译流水线，支持字幕翻译、TTS 配音、封面生成和 Bilibili 发布。

## 快速开始

```bash
python youtube-video-translator/scripts/phase_runner.py run --video-id <ID>

# 分阶段运行
python youtube-video-translator/scripts/phase_runner.py run --video-id <ID> --phase N
```

详细流水线说明见 [docs/phases.md](../../docs/phases.md)。

## 状态管理

```bash
# 查看状态
python youtube-video-translator/scripts/phase_runner.py status --video-id <ID>

# 重置状态
python youtube-video-translator/scripts/phase_runner.py reset --video-id <ID>
```

状态文件存储于 `~/.youtube-video-translator/state/`。

## 目录结构

```
youtube-video-translator/
├── agents/              # 子代理指令文档
│   ├── cover.md
│   ├── description.md
│   └── uploader.md
├── references/          # 权威定义
│   └── phases.md        # 流水线阶段最终权威
├── scripts/
│   ├── phase_runner.py  # 统一执行器
│   ├── core/            # 核心工具
│   ├── phase_0/         # 环境验证
│   ├── phase_3/         # 元数据/字幕发现/下载
│   ├── phase_4/         # 翻译流水线
│   ├── phase_5/         # TTS 配音
│   ├── phase_6/         # 视频合成
│   ├── phase_11/        # 清理
│   └── ...
└── README.md
```
