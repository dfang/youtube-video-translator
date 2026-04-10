import os
import sys
import shutil
from pathlib import Path

_dev_root = Path(__file__).resolve().parent.parent.parent
SKILL_ROOT = _dev_root
sys.path.insert(0, str(SKILL_ROOT / "scripts"))
sys.path.insert(0, str(SKILL_ROOT / "scripts/core"))

def cleanup_temp_files(temp_dir):
    """
    删除指定的临时文件夹及其所有内容。
    """
    if os.path.exists(temp_dir):
        print(f"正在清理临时文件: {temp_dir}...")
        try:
            shutil.rmtree(temp_dir)
            print("清理完成。")
        except Exception as e:
            print(f"清理失败: {e}")
    else:
        print(f"未找到临时文件夹: {temp_dir}，跳过清理。")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python cleaner.py [TempDir]")
        sys.exit(1)

    t_dir = sys.argv[1]
    cleanup_temp_files(t_dir)
