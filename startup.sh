#!/bin/bash
# Azure Web App startup script - minimal, no pip install
# Dependencies are installed during Azure's build phase

cd /home/site/wwwroot

# Create persistent logs directory (matches settings.LOG_DIR=/home/logs on Azure;
# /home persists across restarts and is writable, unlike read-only wwwroot)
mkdir -p /home/logs/sessions /home/logs/summaries

echo "Starting Puzzle Web App..."
echo "Mode: Study (--run_study)"

# Use gunicorn with eventlet for WebSocket support
# Azure provides the Python environment, no venv needed
gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:8000 --timeout 120 "web_app:app"
