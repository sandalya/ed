#!/bin/bash
cd /home/sashok/.openclaw/workspace/ed
source venv/bin/activate
python3 main.py run --transport telegram --judge haiku --budget 1.0 2>&1 | grep -v "httpx\|libssl\|Connecting to\|Connection to\|Disconnecting\|Disconnection"
