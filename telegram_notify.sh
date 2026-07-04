#!/bin/bash
# telegram_notify.sh - Run PolyStrat agent and send output to Telegram
# Replace the token and chat_id with your own if needed.
BOT_TOKEN="8653469154:AAGs-9pIHwG079aftFqpWoWH30bx6lVk5po"
CHAT_ID="8401752292"

cd /root/polystrat-agent
OUTPUT=$(python3 polystrat_agent.py 2>&1)
if [ -n "$OUTPUT" ]; then
    curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        -d chat_id="${CHAT_ID}" \
        -d text="${OUTPUT}" \
        -d parse_mode="Markdown" >/dev/null
fi