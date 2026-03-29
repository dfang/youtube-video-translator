#!/bin/bash
set -e

# YouTube Video Translator Skill Installer
# Environment: macOS (Mac mini M4)

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="youtube-video-translator"
DEST_DIR="$HOME/.agents/skills/$SKILL_DIR"

echo "Installing YouTube Video Translator..."

# 1. Dependency Check
echo "Checking system dependencies..."
for cmd in ffmpeg yt-dlp python3 pip3; do
    if ! command -v "$cmd" &> /dev/null; then
        echo "Error: $cmd is not installed."
        exit 1
    fi
done

# 2. Python Package Installation
echo "Installing/Updating Python dependencies..."
# Pillow, edge-tts, whisperx are core dependencies
# yt-dlp is also available as a python package
pip3 install --upgrade edge-tts Pillow whisperx yt-dlp --quiet

# 3. Create parent directories
mkdir -p "$HOME/.agents/skills"
mkdir -p "$HOME/.claude/skills"
mkdir -p "$HOME/.openclaw/skills"

# 4. Clean up old installation
if [ -d "$DEST_DIR" ]; then
    echo "Cleaning up existing installation at $DEST_DIR..."
    rm -rf "$DEST_DIR"
fi

# 5. Copy Skill to destination
if [ -d "$SRC_DIR/$SKILL_DIR" ]; then
    echo "Copying files to $DEST_DIR..."
    cp -rf "$SRC_DIR/$SKILL_DIR" "$DEST_DIR"
    # Make scripts executable
    chmod +x "$DEST_DIR/scripts/"*.py
else
    echo "Error: Source directory $SRC_DIR/$SKILL_DIR not found."
    exit 1
fi

# 6. Create symlinks (idempotent on macOS using -n)
echo "Creating symlinks..."
ln -shf "$DEST_DIR" "$HOME/.claude/skills/$SKILL_DIR"
ln -shf "$DEST_DIR" "$HOME/.openclaw/skills/$SKILL_DIR"

echo "----------------------------------------------------"
echo "Successfully installed to: $DEST_DIR"
echo "Symlinked to:"
echo "  - $HOME/.claude/skills/$SKILL_DIR"
echo "  - $HOME/.openclaw/skills/$SKILL_DIR"
echo "Done."
