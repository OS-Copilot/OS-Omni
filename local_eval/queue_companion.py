"""Keep the ongoing evaluation awake and refresh its report on status changes."""
import ctypes
import sys
import time
from pathlib import Path
import psutil

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from local_eval.summarize import summarize

pid=int(sys.argv[1])
queue_process=psutil.Process(pid)
started=queue_process.create_time()
ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
last=None
try:
    while psutil.pid_exists(pid) and psutil.Process(pid).create_time()==started:
        path=ROOT/'local_eval/queue/status.json'
        stamp=path.stat().st_mtime_ns if path.exists() else 0
        if stamp!=last:
            try:
                summarize();last=stamp
            except (OSError,ValueError):
                pass
        time.sleep(15)
finally:
    summarize()
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
