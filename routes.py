"""
Flask HTTP routes for puzzle collaboration web app.
Registered as a Blueprint in web_app.py.
"""
from flask import Blueprint, render_template, request, session, redirect, url_for, send_file
import os
import uuid
import time
import zipfile
import tempfile
from datetime import datetime

from game_session import (
    user_sessions, get_user_session_id, get_game_session,
    get_auto_player_modes, LOGGING_AVAILABLE
)

# Import authentication (only used in study mode)
try:
    from utils.auth_manager import auth_manager
    AUTH_AVAILABLE = True
except ImportError:
    AUTH_AVAILABLE = False

# Import logger factory if available
if LOGGING_AVAILABLE:
    from web_logger import get_user_session_logger

puzzle_routes = Blueprint('puzzle', __name__)


# ============================================================================
# HTTP Request Logging Middleware
# ============================================================================

@puzzle_routes.before_request
def log_http_request():
    """Log HTTP requests."""
    if LOGGING_AVAILABLE:
        session_id = get_user_session_id()
        if session_id and session_id in user_sessions:
            game_session = user_sessions[session_id]
            if game_session.session_logger:
                # Store request start time for duration calculation
                request.start_time = time.time()
                game_session.session_logger.log_http_request(
                    session_id=session_id,
                    method=request.method,
                    path=request.path,
                    status_code=None  # Will be updated in after_request
                )


@puzzle_routes.after_request
def log_http_response(response):
    """Log HTTP response with duration."""
    if LOGGING_AVAILABLE and hasattr(request, 'start_time'):
        session_id = get_user_session_id()
        if session_id and session_id in user_sessions:
            game_session = user_sessions[session_id]
            if game_session.session_logger:
                duration_ms = (time.time() - request.start_time) * 1000
                game_session.session_logger.log_http_request(
                    session_id=session_id,
                    method=request.method,
                    path=request.path,
                    status_code=response.status_code,
                    duration_ms=duration_ms
                )
    return response


# ============================================================================
# Flask Routes
# ============================================================================

@puzzle_routes.route('/')
def index():
    """Landing page to select role."""
    from flask import current_app
    RUN_STUDY_MODE = current_app.config.get('RUN_STUDY_MODE', False)
    AUTO_START_MODE = current_app.config.get('AUTO_START_MODE')
    SHARED_VIEW_ENABLED = current_app.config.get('SHARED_VIEW_ENABLED', True)

    # If study mode is enabled, check consent and authentication
    if RUN_STUDY_MODE:
        # Store URL parameters in session if provided
        if request.args.get('PROLIFIC_PID'):
            session['url_prolific_pid'] = request.args.get('PROLIFIC_PID')
        if request.args.get('STUDY_ID'):
            session['url_study_id'] = request.args.get('STUDY_ID')
        
        if not session.get('consent_given', False):
            return redirect(url_for('puzzle.consent'))
        if not session.get('authenticated', False):
            return redirect(url_for('puzzle.login'))
    
    # Priority 1: Command-line flags (if set, override everything)
    auto_modes = get_auto_player_modes(AUTO_START_MODE)
    if auto_modes is not None:
        return redirect(url_for(
            f'puzzle.{AUTO_START_MODE}',
            auto_worker=auto_modes[0],
            auto_helper=auto_modes[1],
            shared_view='true' if SHARED_VIEW_ENABLED else 'false',
        ))
    
    # Priority 2: Credential-based function (if authenticated and not admin)
    if session.get('authenticated'):
        is_admin = session.get('role') == 'admin'
        user_function = session.get('user_function')
        
        # Admins can choose their role manually
        if is_admin:
            print(f"[DEBUG] Admin user - showing role selection")
            return render_template('index.html', is_admin=True)
        
        # Non-admin users: auto-redirect based on their function
        if user_function == 'helper':
            print(f"[DEBUG] Auto-redirecting to helper view based on credentials")
            
            if LOGGING_AVAILABLE:
                session_id = get_user_session_id()
                if session_id:
                    user_logger = get_user_session_logger()
                    user_logger.log_action(
                        session_id=session_id,
                        action_type='system_event',
                        event_name='auto_redirect_helper',
                        details={'user_function': user_function, 'source': 'credentials'},
                        metadata={}
                    )
            
            return redirect(url_for('puzzle.helper', auto_worker='llm', auto_helper='human', shared_view='true' if SHARED_VIEW_ENABLED else 'false'))
        elif user_function == 'worker':
            print(f"[DEBUG] Auto-redirecting to worker view based on credentials")
            
            if LOGGING_AVAILABLE:
                session_id = get_user_session_id()
                if session_id:
                    user_logger = get_user_session_logger()
                    user_logger.log_action(
                        session_id=session_id,
                        action_type='system_event',
                        event_name='auto_redirect_worker',
                        details={'user_function': user_function, 'source': 'credentials'},
                        metadata={}
                    )
            
            return redirect(url_for('puzzle.worker', auto_worker='human', auto_helper='llm', shared_view='true' if SHARED_VIEW_ENABLED else 'false'))
        else:
            print(f"[DEBUG] User function not set or invalid: {user_function}")
            
            if LOGGING_AVAILABLE:
                session_id = get_user_session_id()
                if session_id:
                    user_logger = get_user_session_logger()
                    user_logger.log_action(
                        session_id=session_id,
                        action_type='system_event',
                        event_name='manual_selection_fallback',
                        details={'reason': 'invalid_or_missing_function', 'user_function': user_function},
                        metadata={}
                    )
            
            return render_template('index.html', is_admin=False)
    
    # Priority 3: Manual selection (not authenticated or no auto-start mode)
    is_admin = session.get('role') == 'admin'
    return render_template('index.html', is_admin=is_admin)


@puzzle_routes.route('/login', methods=['GET', 'POST'])
def login():
    """Display login form and handle authentication."""
    from flask import current_app
    RUN_STUDY_MODE = current_app.config.get('RUN_STUDY_MODE', False)

    if not RUN_STUDY_MODE:
        return redirect(url_for('puzzle.index'))
    
    if not AUTH_AVAILABLE:
        return render_template('error.html', error="Authentication system not available"), 500
    
    # Check if consent given first
    if not session.get('consent_given', False):
        if request.args.get('PROLIFIC_PID'):
            session['url_prolific_pid'] = request.args.get('PROLIFIC_PID')
        if request.args.get('STUDY_ID'):
            session['url_study_id'] = request.args.get('STUDY_ID')
        if request.args.get('SESSION_ID'):
            session['url_session_id'] = request.args.get('SESSION_ID')
        session.modified = True
        return redirect(url_for('puzzle.consent', 
                               PROLIFIC_PID=request.args.get('PROLIFIC_PID'),
                               STUDY_ID=request.args.get('STUDY_ID'),
                               SESSION_ID=request.args.get('SESSION_ID')))
    
    # If already authenticated, redirect to index
    if session.get('authenticated', False):
        return redirect(url_for('puzzle.index'))
    
    if request.method == 'POST':
        user_id = request.form.get('user_id', '').strip()
        token = request.form.get('token', '').strip()
        study_id = request.form.get('study_id', '').strip()
        custom_session_id = request.form.get('session_id', '').strip()
        prolific_pid = request.form.get('prolific_pid', '').strip()
        
        validation = auth_manager.validate_user_credentials(user_id, token, study_id)
        
        if validation.valid:
            session.permanent = True
            session['authenticated'] = True
            session['user_id'] = user_id
            session['token'] = token
            session['study_id'] = study_id if study_id else None
            session['prolific_pid'] = prolific_pid if prolific_pid else None
            session['role'] = validation.user_data.get('role', 'participant')
            session['user_function'] = validation.user_data.get('function', 'worker')
            
            game_session_id = str(uuid.uuid4())
            session['game_session_id'] = game_session_id
            print(f"[Session] Generated unique game session ID: {game_session_id} for user {user_id}")
            
            if custom_session_id:
                session['custom_session_id'] = custom_session_id
                print(f"[Session] Also storing custom session ID for logging: {custom_session_id}")
            
            if LOGGING_AVAILABLE:
                session_id = get_user_session_id()
                if session_id:
                    user_logger = get_user_session_logger()
                    user_logger.log_action(
                        session_id=session_id,
                        action_type='system_event',
                        event_name='login_success',
                        details={
                            'user_id': user_id,
                            'study_id': study_id,
                            'custom_session_id': custom_session_id,
                            'prolific_pid': prolific_pid,
                            'role': validation.user_data.get('role', 'participant'),
                            'function': validation.user_data.get('function', 'worker')
                        },
                        metadata={}
                    )
            
            print(f"[DEBUG] User {user_id} authenticated with function: {session['user_function']}, role: {session['role']}")
            return redirect(url_for('puzzle.index'))
        else:
            if LOGGING_AVAILABLE:
                temp_session_id = request.sid if hasattr(request, 'sid') else 'unknown'
                user_logger = get_user_session_logger()
                user_logger.log_action(
                    session_id=temp_session_id,
                    action_type='system_event',
                    event_name='login_failure',
                    details={
                        'user_id': user_id,
                        'study_id': study_id,
                        'error': validation.error
                    },
                    metadata={}
                )
            
            return render_template('login.html', error=validation.error,
                                 prefill_study_id=study_id,
                                 prefill_session_id=custom_session_id,
                                 prefill_prolific_pid=prolific_pid)
    
    # GET request - show login form with pre-filled values
    prolific_pid = request.args.get('PROLIFIC_PID') or session.get('url_prolific_pid', '')
    study_id = request.args.get('STUDY_ID') or session.get('url_study_id', '')
    custom_session_id = request.args.get('SESSION_ID') or session.get('url_session_id', '')
    
    return render_template('login.html', 
                         prefill_prolific_pid=prolific_pid,
                         prefill_study_id=study_id,
                         prefill_session_id=custom_session_id)


@puzzle_routes.route('/consent')
def consent():
    """Display consent form."""
    from flask import current_app
    RUN_STUDY_MODE = current_app.config.get('RUN_STUDY_MODE', False)

    if not RUN_STUDY_MODE:
        return redirect(url_for('puzzle.index'))
    
    if request.args.get('PROLIFIC_PID'):
        session['url_prolific_pid'] = request.args.get('PROLIFIC_PID')
    if request.args.get('STUDY_ID'):
        session['url_study_id'] = request.args.get('STUDY_ID')
    if request.args.get('SESSION_ID'):
        session['url_session_id'] = request.args.get('SESSION_ID')
    session.modified = True
    
    if session.get('consent_given', False):
        if not session.get('authenticated', False):
            return redirect(url_for('puzzle.login',
                                   PROLIFIC_PID=request.args.get('PROLIFIC_PID'),
                                   STUDY_ID=request.args.get('STUDY_ID'),
                                   SESSION_ID=request.args.get('SESSION_ID')))
        return redirect(url_for('puzzle.index'))
    
    return render_template('consent.html')


@puzzle_routes.route('/consent/accept', methods=['POST'])
def consent_accept():
    """Handle consent acceptance."""
    from flask import current_app
    RUN_STUDY_MODE = current_app.config.get('RUN_STUDY_MODE', False)

    session.permanent = True
    session['consent_given'] = True
    
    if LOGGING_AVAILABLE:
        session_id = get_user_session_id()
        if session_id:
            user_logger = get_user_session_logger()
            user_logger.log_action(
                session_id=session_id,
                action_type='system_event',
                event_name='consent_accepted',
                details={'timestamp': datetime.now().isoformat()},
                metadata={}
            )
    
    if RUN_STUDY_MODE and not session.get('authenticated', False):
        return redirect(url_for('puzzle.login'))
    
    return redirect(url_for('puzzle.index'))


@puzzle_routes.route('/consent/decline', methods=['POST'])
def consent_decline():
    """Handle consent decline."""
    if LOGGING_AVAILABLE:
        session_id = get_user_session_id()
        if session_id:
            user_logger = get_user_session_logger()
            user_logger.log_action(
                session_id=session_id,
                action_type='system_event',
                event_name='consent_declined',
                details={'timestamp': datetime.now().isoformat()},
                metadata={}
            )
    
    return render_template('consent_declined.html')


@puzzle_routes.route('/logout')
def logout():
    """Log out the current user."""
    session_id = get_user_session_id()
    game_session = get_game_session()
    if game_session and game_session.session_logger:
        trial_info = game_session.get_trial_info()
        game_session.session_logger.end_session(
            session_id=session_id,
            summary_data={
                'puzzles_completed': trial_info['current'] if game_session.trial_active else trial_info['current'] - 1,
                'puzzles_attempted': trial_info['current'],
                'total_puzzles': trial_info['total'],
                'total_messages': len(game_session.chat_history),
                'logout_reason': 'user_initiated'
            }
        )
    
    session.clear()
    return redirect(url_for('puzzle.consent'))


@puzzle_routes.route('/reset')
def reset():
    """Reset session (for debugging)."""
    session.clear()
    return redirect(url_for('puzzle.index'))


@puzzle_routes.route('/worker')
def worker():
    """Worker interface."""
    from flask import current_app
    RUN_STUDY_MODE = current_app.config.get('RUN_STUDY_MODE', False)

    if RUN_STUDY_MODE:
        if not session.get('consent_given', False):
            return redirect(url_for('puzzle.consent'))
        if not session.get('authenticated', False):
            return redirect(url_for('puzzle.login'))
    
    # Explicit shared room id enables human-human pairing across browsers (?session=<id>)
    shared_session = request.args.get('session')
    if shared_session:
        session['game_session_id'] = shared_session
        session.modified = True

    if not session.get('game_session_id'):
        game_session_id = str(uuid.uuid4())
        session['game_session_id'] = game_session_id
        session.modified = True
        print(f"[ROUTE-DEBUG] Generated NEW game_session_id: {game_session_id}")
    else:
        game_session_id = session.get('game_session_id')
        print(f"[ROUTE-DEBUG] Using EXISTING game_session_id: {game_session_id}")
    
    user_id = session.get('user_id', 'anonymous')
    print(f"[ROUTE-DEBUG] /worker accessed by user_id={user_id}, game_session_id={game_session_id}")
    
    auto_worker, auto_helper = get_auto_player_modes(current_app.config.get('AUTO_START_MODE')) or (
        request.args.get('auto_worker'),
        request.args.get('auto_helper'),
    )
    shared_view = request.args.get('shared_view', 'true')
    questionnaire_url = os.environ.get('FORMS_QUESTIONNAIRE_URL', '')
    return render_template('worker.html', auto_worker=auto_worker, auto_helper=auto_helper, shared_view=shared_view, questionnaire_url=questionnaire_url)


@puzzle_routes.route('/helper')
def helper():
    """Helper interface."""
    from flask import current_app
    RUN_STUDY_MODE = current_app.config.get('RUN_STUDY_MODE', False)

    if RUN_STUDY_MODE:
        if not session.get('consent_given', False):
            return redirect(url_for('puzzle.consent'))
        if not session.get('authenticated', False):
            return redirect(url_for('puzzle.login'))
    
    # Explicit shared room id enables human-human pairing across browsers (?session=<id>)
    shared_session = request.args.get('session')
    if shared_session:
        session['game_session_id'] = shared_session
        session.modified = True

    if not session.get('game_session_id'):
        game_session_id = str(uuid.uuid4())
        session['game_session_id'] = game_session_id
        session.modified = True
        print(f"[ROUTE-DEBUG] Generated NEW game_session_id for helper: {game_session_id}")
    else:
        game_session_id = session.get('game_session_id')
        print(f"[ROUTE-DEBUG] Using EXISTING game_session_id for helper: {game_session_id}")
    
    auto_worker, auto_helper = get_auto_player_modes(current_app.config.get('AUTO_START_MODE')) or (
        request.args.get('auto_worker'),
        request.args.get('auto_helper'),
    )
    shared_view = request.args.get('shared_view', 'true')
    questionnaire_url = os.environ.get('FORMS_QUESTIONNAIRE_URL', '')
    return render_template('helper.html', auto_worker=auto_worker, auto_helper=auto_helper, shared_view=shared_view, questionnaire_url=questionnaire_url)


@puzzle_routes.route('/admin/download_logs')
def download_logs():
    """Download all logs as a zip file (admin only)."""
    if session.get('role') != 'admin':
        return render_template('error.html', error="Access denied. Admin privileges required."), 403
    
    # Use the same LOG_DIR the loggers write to (absolute, anchored to the puzzle
    # dir) so the zip always reflects the live logs regardless of working dir.
    try:
        from utils import settings
        logs_dir = settings.LOG_DIR
    except Exception:
        logs_dir = os.path.join(os.path.dirname(__file__), 'logs')
    
    if not os.path.exists(logs_dir):
        return render_template('error.html', error="Logs directory not found."), 404
    
    temp_zip = tempfile.NamedTemporaryFile(mode='w+b', suffix='.zip', delete=False)
    temp_zip_path = temp_zip.name
    temp_zip.close()
    
    try:
        with zipfile.ZipFile(temp_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(logs_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, logs_dir)
                    zipf.write(file_path, arcname)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        download_filename = f'puzzle_logs_{timestamp}.zip'
        
        if LOGGING_AVAILABLE:
            session_id = get_user_session_id()
            if session_id:
                user_logger = get_user_session_logger()
                user_logger.log_action(
                    session_id=session_id,
                    action_type='system_event',
                    event_name='admin_download_logs',
                    details={
                        'user_id': session.get('user_id'),
                        'timestamp': timestamp,
                        'filename': download_filename
                    },
                    metadata={}
                )
        
        return send_file(
            temp_zip_path,
            mimetype='application/zip',
            as_attachment=True,
            download_name=download_filename
        )
    
    except Exception as e:
        if os.path.exists(temp_zip_path):
            os.unlink(temp_zip_path)
        print(f"[ERROR] Failed to create logs zip: {e}")
        import traceback
        traceback.print_exc()
        return render_template('error.html', error=f"Failed to create logs archive: {str(e)}"), 500
    
    finally:
        pass
