#!/bin/bash
# Minimal Azure startup script - no venv, no pip
# Just run the app using whatever Python environment is available

echo "MINIMAL STARTUP v1"
date

cd /home/site/wwwroot

# Create persistent logs directory (matches settings.LOG_DIR=/home/logs on Azure)
mkdir -p /home/logs/sessions /home/logs/summaries

# Just run the app
python3 web_app.py --run_study
