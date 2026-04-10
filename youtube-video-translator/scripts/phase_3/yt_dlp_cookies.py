#!/usr/bin/env python3
"""
Helpers for yt-dlp browser-cookie detection.

This intentionally does not use a short hard timeout. On some systems,
reading/decrypting browser cookies can take longer than expected.
"""
from __future__ import annotations

import sys
import subprocess
from pathlib import Path

_dev_root = Path(__file__).resolve().parent.parent.parent
SKILL_ROOT = _dev_root
sys.path.insert(0, str(SKILL_ROOT / "scripts"))
sys.path.insert(0, str(SKILL_ROOT / "scripts/core"))


def detect_browser_cookie_args(browser: str = "chrome") -> tuple[list[str], str | None]:
    """
    Return yt-dlp cookie args if browser cookies are available.

    Returns:
      (["--cookies-from-browser", browser], None) on success
      ([], error_message) on failure
    """
    cmd = ["yt-dlp", "--cookies-from-browser", browser, "--dump-json", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return [], "yt-dlp not found while probing browser cookies"
    except Exception as exc:
        return [], f"browser cookie probe raised unexpected error: {exc}"

    if result.returncode == 0:
        return ["--cookies-from-browser", browser], None

    stderr = (result.stderr or "").strip()
    stdout = (result.stdout or "").strip()
    detail = stderr or stdout or f"yt-dlp exited with code {result.returncode}"
    return [], detail[:1000]
