#!/bin/bash
cd /home/sashok/.openclaw/workspace/ed
source venv/bin/activate
python3 test_abby.py 2>&1 | grep -v "httpx\|libssl\|Connecting to\|Connection to\|Disconnecting\|Disconnection"
