import os
import subprocess
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parent
old_pid = int(sys.argv[1])
for _ in range(50):
    try:
        os.kill(old_pid, 0)
        time.sleep(0.2)
    except OSError:
        break
result = subprocess.run(["git", "pull", "--ff-only", "origin", "main"], cwd=root, capture_output=True, text=True)
if result.returncode:
    log = root / "update_error.txt"
    log.write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
subprocess.Popen([sys.executable, str(root / "main.py")], cwd=root)
