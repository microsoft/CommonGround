"""
Flask web application for puzzle collaboration task.
Supports human workers with LLM helpers.

Usage:
    python web_app.py                    # Default: select roles manually
    python web_app.py --worker           # Human worker with AI helper
    python web_app.py --helper           # AI worker with human helper
    
    Then navigate to http://localhost:5000
"""
from flask import Flask
from flask_socketio import SocketIO
from dotenv import load_dotenv
import argparse
import os
import secrets


load_dotenv()


def _env_bool(name, default=False):
    value = os.environ.get(name)
    return default if value is None else value.lower() in {'1', 'true', 'yes', 'on'}


# Create Flask app and SocketIO
app = Flask(__name__)
flask_secret_key = os.environ.get('FLASK_SECRET_KEY')
app.config['SECRET_KEY'] = flask_secret_key or secrets.token_urlsafe(32)
app.config['SESSION_COOKIE_NAME'] = 'puzzle_session'
app.config['PERMANENT_SESSION_LIFETIME'] = 86400  # 24 hours in seconds
app.config['SESSION_PERMANENT'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Config flags (CLI options override these when running web_app.py directly)
app.config['AUTO_START_MODE'] = os.environ.get('AUTO_START_MODE') or None
app.config['SHARED_VIEW_ENABLED'] = _env_bool('SHARED_VIEW_ENABLED', True)
app.config['RUN_STUDY_MODE'] = _env_bool('RUN_STUDY_MODE', False)

allowed_origins = os.environ.get('SOCKETIO_ALLOWED_ORIGINS')
if allowed_origins:
    allowed_origins = [origin.strip() for origin in allowed_origins.split(',') if origin.strip()]

socketio = SocketIO(
    app,
    cors_allowed_origins=allowed_origins,
    manage_session=False,
    cookie=None,
    ping_timeout=60,
    ping_interval=25,
    async_mode='threading'
)

# Register routes blueprint
from routes import puzzle_routes
app.register_blueprint(puzzle_routes)

# Register socket handlers
from socket_handlers import register_handlers
register_handlers(socketio, app)


@app.get('/healthz')
def healthz():
    return {'status': 'ok'}


@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response


def run_server(mode=None, shared_view=True, run_study=False, host=None, port=None, debug=None):
    """Configure app.config and start the Flask-SocketIO server.

    mode: None = manual role selection (human-human, or pick per browser),
    'worker' = human worker + AI helper, 'helper' = AI worker + human helper.
    """
    app.config['AUTO_START_MODE'] = mode
    app.config['SHARED_VIEW_ENABLED'] = shared_view
    app.config['RUN_STUDY_MODE'] = run_study

    if host is None:
        host = '0.0.0.0'
    if port is None:
        port = int(os.environ.get('PORT', 5000))
    if debug is None:
        debug = os.environ.get('FLASK_DEBUG', '1') == '1'

    labels = {
        None: 'Manual selection (human-human, or choose AI per browser)',
        'worker': 'Human Worker + AI Helper',
        'helper': 'AI Worker + Human Helper',
    }
    print(f"[mode] {labels.get(mode, mode)}{'' if shared_view else ' (non-shared view)'}")
    if run_study:
        print("[study] Login required")
    print(f"[serve] http://localhost:{port}  (worker: /worker, helper: /helper)")

    socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)


if __name__ == '__main__':
    """
    ============================================================================
    ROLE ASSIGNMENT SYSTEM (Hybrid Approach - Option 3)
    ============================================================================
    
    This application supports three methods of role assignment with the following priority:
    
    1. COMMAND-LINE FLAGS (Highest Priority)
       - Use --worker or --helper to force a specific mode
       - Overrides all other settings
       - Useful for: Testing, demos, manual configuration
       
    2. CREDENTIAL-BASED AUTO-ASSIGNMENT (Medium Priority)
       - After login, reads 'function' field from user credentials
       - Automatically redirects users to their assigned role
       - Admin users are exempt and can choose manually
       - Useful for: Study deployments where participants are pre-assigned
       
    3. MANUAL SELECTION (Lowest Priority)
       - Users see index page and choose their role
       - Available when: Not authenticated OR admin user
       - Useful for: Open access, admin override
       
    Credentials Format (user_credentials.json):
    {
      "users": {
        "user_id": {
          "token": "...",
          "role": "participant|admin",
          "function": "worker|helper"  // <- Determines auto-assignment
        }
      }
    }
    ============================================================================
    """
    
    parser = argparse.ArgumentParser(
        description='Puzzle Collaboration Web App',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python web_app.py                       # Manual role selection OR credential-based auto-assignment
  python web_app.py --worker              # Force human worker mode (overrides credentials)
  python web_app.py --helper              # Force human helper mode (overrides credentials)
  python web_app.py --worker --no_shared_view  # Human worker with AI helper (non-shared view)
  python web_app.py --run_study           # Study mode with credential-based role assignment

Role Assignment Priority:
  1. Command-line flags (--worker or --helper) - Overrides everything
  2. User credentials 'function' field - Auto-assigns role after login
  3. Manual selection - User chooses role if not authenticated
  
  Note: Admin users always see manual role selection regardless of their 'function' field.
        """
    )
    
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        '--worker',
        action='store_true',
        help='Start as human worker with AI helper'
    )
    mode_group.add_argument(
        '--helper',
        action='store_true',
        help='Start as human helper with AI worker'
    )
    
    parser.add_argument(
        '--no_shared_view',
        action='store_true',
        help='Disable shared view (helper cannot see worker progress in real-time)'
    )
    
    parser.add_argument(
        '--run_study',
        action='store_true',
        help='Enable study mode (requires login before starting)'
    )
    
    args = parser.parse_args()

    mode = 'worker' if args.worker else ('helper' if args.helper else None)
    run_server(mode=mode, shared_view=not args.no_shared_view, run_study=args.run_study)
