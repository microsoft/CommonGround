#!/bin/bash
# Bash script to run the puzzle collaboration web app on Ubuntu
# Usage: ./run_web_app.sh [options]
#
# Options:
#   --worker        Start as human worker with AI helper (default)
#   --helper        Start as AI worker with human helper
#   --no-shared     Disable shared view (helper cannot see worker's progress)
#   --study         Enable study mode (requires consent form)
#   --port PORT     Specify port (default: 5000)
#   --host HOST     Specify host (default: 0.0.0.0)
#   --dev           Development mode (debug enabled)

set -e  # Exit on error

# Color codes for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Default values
PORT=5000
HOST="0.0.0.0"
MODE_ARGS="--run_study"
DEV_MODE=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --worker)
            MODE_ARGS="--worker"
            shift
            ;;
        --helper)
            MODE_ARGS="--helper"
            shift
            ;;
        --no-shared)
            MODE_ARGS="${MODE_ARGS} --no_shared_view"
            shift
            ;;
        --study)
            if [[ ! $MODE_ARGS == *"--run_study"* ]]; then
                MODE_ARGS="${MODE_ARGS} --run_study"
            fi
            shift
            ;;
        --port)
            PORT="$2"
            shift 2
            ;;
        --host)
            HOST="$2"
            shift 2
            ;;
        --dev)
            DEV_MODE=true
            shift
            ;;
        --help)
            echo "Usage: ./run_web_app.sh [options]"
            echo ""
            echo "Options:"
            echo "  --worker        Start as human worker with AI helper (default)"
            echo "  --helper        Start as AI worker with human helper"
            echo "  --no-shared     Disable shared view"
            echo "  --study         Enable study mode (requires consent form)"
            echo "  --port PORT     Specify port (default: 5000)"
            echo "  --host HOST     Specify host (default: 0.0.0.0)"
            echo "  --dev           Development mode (debug enabled)"
            echo "  --help          Show this help message"
            echo ""
            echo "Examples:"
            echo "  ./run_web_app.sh"
            echo "  ./run_web_app.sh --worker --study"
            echo "  ./run_web_app.sh --helper --port 8080"
            echo "  ./run_web_app.sh --worker --no-shared --dev"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

echo "=========================================="
echo "SCRIPT VERSION: 2026-05-12-v3"
echo "=========================================="
echo -e "${GREEN}Starting Puzzle Collaboration Web App...${NC}"
echo ""

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python 3 is not installed.${NC}"
    echo "Install it with: sudo apt update && sudo apt install python3 python3-pip python3-venv"
    exit 1
fi

# Check Python version (need 3.8+)
PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 8 ]); then
    echo -e "${RED}Error: Python 3.8 or higher is required. Current version: $PYTHON_VERSION${NC}"
    exit 1
fi

echo -e "${CYAN}Python version: $PYTHON_VERSION ✓${NC}"

# Reuse packages supplied by an external Python environment.
if [ -n "$PYTHONPATH" ] && python3 -c "import flask" 2>/dev/null; then
    echo -e "${GREEN}Packages already available. Skipping venv creation.${NC}"
    SKIP_VENV=true
else
    SKIP_VENV=false
    # Kill any running web_app.py processes
    echo -e "${YELLOW}Checking for running web_app.py processes...${NC}"
    pkill -f web_app.py 2>/dev/null && echo -e "${CYAN}Stopped existing web_app.py process${NC}" || echo -e "${CYAN}No running web_app.py process found${NC}"
    sleep 1
fi

# Create logs directory
mkdir -p logs/sessions logs/summaries

if [ "$SKIP_VENV" = false ]; then
    # Local development: use venv
    # Check if virtual environment exists
    if [ -d "venv" ]; then
        echo -e "${YELLOW}Removing existing virtual environment...${NC}"
        rm -rf venv
    fi

    echo -e "${YELLOW}Creating virtual environment...${NC}"
    python3 -m venv venv

    echo -e "${YELLOW}Installing dependencies...${NC}"
    source venv/bin/activate

    # Upgrade pip
    pip install --upgrade pip

    # Install requirements with maximum verbosity for log streaming
    echo "=== PIP INSTALL STARTING ==="
    date
    export PYTHONUNBUFFERED=1
    if [ -f "requirements.txt" ]; then
        pip install -vvv --no-cache-dir --progress-bar off -r requirements.txt
    else
        echo -e "${RED}Error: No requirements file found (requirements.txt)${NC}"
        exit 1
    fi
    echo "=== PIP INSTALL FINISHED ==="
    date

    echo -e "${GREEN}Dependencies installed successfully!${NC}"

    # Check if .env file exists
    if [ ! -f ".env" ]; then
        echo -e "${YELLOW}Warning: .env file not found. Some features may not work correctly.${NC}"
        echo -e "${YELLOW}Create a .env file with required environment variables.${NC}"
    fi
fi

echo ""
echo -e "${CYAN}======================================${NC}"
echo -e "${GREEN}Starting web server...${NC}"
echo -e "${CYAN}======================================${NC}"
echo ""
echo -e "${YELLOW}Configuration:${NC}"
echo -e "  Host: ${CYAN}$HOST${NC}"
echo -e "  Port: ${CYAN}$PORT${NC}"
echo -e "  Mode: ${CYAN}$MODE_ARGS${NC}"
if [ "$DEV_MODE" = true ]; then
    echo -e "  Debug: ${CYAN}enabled${NC}"
fi
echo ""
echo -e "${YELLOW}Access the app at:${NC}"

if [ "$HOST" = "0.0.0.0" ]; then
    # Get the server's IP address
    SERVER_IP=$(hostname -I | awk '{print $1}')
    echo -e "  ${CYAN}http://localhost:$PORT${NC} (local)"
    if [ -n "$SERVER_IP" ]; then
        echo -e "  ${CYAN}http://$SERVER_IP:$PORT${NC} (network)"
    fi
else
    echo -e "  ${CYAN}http://$HOST:$PORT${NC}"
fi

echo ""
echo -e "${CYAN}Interface URLs:${NC}"
echo -e "  Worker: ${CYAN}http://localhost:$PORT/worker${NC}"
echo -e "  Helper: ${CYAN}http://localhost:$PORT/helper${NC}"
echo ""
echo -e "${YELLOW}Logs directory: ${CYAN}logs/${NC}"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop the server${NC}"
echo ""

# Export Flask environment variables
export FLASK_APP=web_app.py
if [ "$DEV_MODE" = true ]; then
    export FLASK_ENV=development
    export FLASK_DEBUG=1
fi

# Trap Ctrl+C to cleanup
trap 'echo -e "\n${YELLOW}Shutting down server...${NC}"; exit 0' INT TERM

# Run the Flask app
echo -e "${GREEN}Starting web_app.py with args: $MODE_ARGS${NC}"
python3 web_app.py $MODE_ARGS

# Deactivate virtual environment on exit (only if we activated one)
if [ "$SKIP_VENV" = false ]; then
    deactivate
fi
