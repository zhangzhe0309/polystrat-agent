#!/usr/bin/env python3
"""
Telegram bridge for PolyStrat agent.
Runs polystrat_agent.py as a subprocess, captures its stdout,
extracts trade signals, and forwards them to Telegram.
"""
import subprocess
import sys
import os
import re
import time
import threading
import requests
from pathlib import Path

# ==== USER CONFIG ====
BOT_TOKEN = "8653469154:AAGs-9pIHwG079aftFqpWoWH30bx6lVk5po"  # from user
CHAT_ID = "8401752292"                     # from user ID
PROJECT_DIR = Path("/root/polystrat-agent")
SCRIPT = PROJECT_DIR / "polystrat_agent.py"
# =====================

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

def send_telegram(text: str):
    """Send a message via Telegram Bot API."""
    payload = {"chat_id": CHAT_ID, "text": text}
    try:
        resp = requests.post(TELEGRAM_API, json=payload, timeout=10)
        if resp.status_code != 200:
            print(f"[Telegram] Error {resp.status_code}: {resp.text}")
        else:
            print(f"[Telegram] Sent: {text[:80]}...")
    except Exception as e:
        print(f"[Telegram] Exception: {e}")

def signal_detector(pipe):
    """Read lines from subprocess stdout, detect signals, send to TG."""
    last_signal = None
    for line in iter(pipe.readline, ""):
        if not line:
            break
        line = line.rstrip()
        print(f"[POL] {line}")  # echo to console for debugging
        # Look for trade execution lines
        if "已模拟下单" in line or "已实盘下单" in line:
            # Simple deduplication: ignore if same line as previous
            if line != last_signal:
                last_signal = line
                # Optionally shorten or keep full line
                msg = f"🤖 *PolySignal*: {line}"
                send_telegram(msg)
        # Also capture summary line at end of run (optional)
        elif "本轮共下单" in line:
            if line != last_signal:
                last_signal = line
                msg = f"📊 *PolySummary*: {line}"
                send_telegram(msg)
    pipe.close()

def main():
    # Ensure we can import local modules
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_DIR) + ":" + env.get("PYTHONPATH", "")
    print("[Bridge] Starting PolyStrat agent...")
    proc = subprocess.Popen(
        [sys.executable, str(SCRIPT)],
        cwd=str(PROJECT_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # merge stderr into stdout
        text=True,
        env=env,
        bufsize=1,  # line-buffered
    )
    # Start a thread to read output and detect signals
    t = threading.Thread(target=signal_detector, args=(proc.stdout,), daemon=True)
    t.start()
    try:
        # Wait for process to exit (it shouldn't unless error)
        proc.wait()
    except KeyboardInterrupt:
        print("\n[Bridge] Received Ctrl+C, terminating...")
        proc.terminate()
        proc.wait()
    print("[Bridge] PolyStrat agent exited.")

if __name__ == "__main__":
    main()