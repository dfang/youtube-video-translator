#!/usr/bin/env python3
"""
Interactive prompt for YouTube Video Translator options.
This script outputs a formatted question for Claude Code's AskUserQuestion tool.
"""

import json
import sys

def main():
    url = sys.argv[1] if len(sys.argv) > 1 else ""

    if not url:
        print("❌ 错误：请提供 YouTube 视频链接")
        sys.exit(1)

    # Output the question structure for Claude Code
    question = {
        "questions": [
            {
                "question": "请选择 YouTube 视频翻译选项",
                "header": "翻译选项",
                "multiSelect": False,
                "options": [
                    {
                        "label": "下载字幕 + 中文配音（默认）",
                        "description": "速度快，使用 YouTube 自带英文字幕 + edge-tts 在线配音"
                    },
                    {
                        "label": "WhisperX 转录 + 中文配音",
                        "description": "质量更高，使用本地转录 + edge-tts 在线配音"
                    },
                    {
                        "label": "下载字幕 + 保留原音",
                        "description": "只添加中文字幕，保留原始音频"
                    },
                    {
                        "label": "WhisperX 转录 + 保留原音",
                        "description": "最高质量转录 + 保留原始音频"
                    }
                ]
            },
            {
                "question": "请选择字幕类型",
                "header": "字幕类型",
                "multiSelect": False,
                "options": [
                    {
                        "label": "仅中文字幕（默认）",
                        "description": "视频底部显示中文字幕"
                    },
                    {
                        "label": "中英文双语字幕",
                        "description": "上方英文 + 下方中文，适合学习"
                    }
                ]
            }
        ]
    }

    # Print as JSON for parsing
    print(json.dumps(question, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
