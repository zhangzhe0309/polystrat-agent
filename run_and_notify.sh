#!/bin/bash
# Run PolyStrat and send output to Telegram
cd /root/polystrat-agent
OUTPUT=$(python3 polystrat_agent.py 2>&1)
# Send to Telegram if there is any output
if [ -n "$OUTPUT" ]; then
    curl -s -X POST "https://api.telegram.org/bot8653469154:AAGs-9pIHwG079aftFqpWoWH30bx6lVk5po/sendMessage" \
        -d chat_id=8401752292 \
        -d text="$OUTPUT" \
        -d parse_mode="Markdown" >/dev/null
fi