#!/bin/bash
# Start the Agent of Agents server
cd "$(dirname "$0")"
pip3 install --break-system-packages -q flask anthropic 2>/dev/null
echo "Starting Agent of Agents on http://localhost:${PORT:-5000}"
python3 app.py
