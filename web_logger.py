"""
User session logging for the puzzle web application.
Logs all user interactions to JSONL files for analysis.
"""
import json
import csv
import hashlib
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional
from threading import Lock

# Import settings with fallback
try:
    from utils import settings
except ImportError:
    import sys
    from pathlib import Path as P
    sys.path.insert(0, str(P(__file__).parent))
    from utils import settings


logger = logging.getLogger(__name__)


class UserSessionLogger:
    """
    Logs all user interactions in the puzzle web app.
    Writes to JSONL (JSON Lines) format for efficient streaming and analysis.
    """
    
    def __init__(self, log_dir: str = None):
        """
        Initialize the user session logger.
        
        Args:
            log_dir: Directory for session logs (defaults to settings.LOG_DIR/sessions)
        """
        base_log_dir = Path(log_dir or settings.LOG_DIR)
        self.log_dir = base_log_dir / "sessions"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        self.summary_dir = base_log_dir / "summaries"
        self.summary_dir.mkdir(parents=True, exist_ok=True)
        
        # Track open file handles and locks for thread safety
        self.session_files = {}  # session_id -> file handle
        self.session_locks = {}  # session_id -> Lock
        self.session_metadata = {}  # session_id -> metadata dict
        
        logger.info(f"UserSessionLogger initialized. Log directory: {self.log_dir}")
    
    def _anonymize_user_id(self, user_id: str) -> str:
        """
        Anonymize user ID using hash if configured.
        
        Args:
            user_id: Original user ID
            
        Returns:
            Anonymized or original user ID based on settings
        """
        if not settings.ANONYMIZE_USER_IDS or not user_id:
            return user_id
        
        # Use SHA256 hash for anonymization
        hash_obj = hashlib.sha256(user_id.encode('utf-8'))
        return f"user_{hash_obj.hexdigest()[:16]}"
    
    def start_session(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        role: str = "unknown",
        config: Dict[str, Any] = None
    ):
        """
        Initialize logging for a new user session.
        
        Args:
            session_id: Unique session identifier
            user_id: User identifier (will be anonymized if configured)
            role: User role (worker/helper)
            config: Session configuration dictionary
        """
        if not settings.LOG_USER_ACTIONS:
            return
        
        # Anonymize user ID if enabled
        anonymized_user_id = self._anonymize_user_id(user_id) if user_id else session_id
        
        # Create session metadata
        self.session_metadata[session_id] = {
            'session_id': session_id,
            'user_id': anonymized_user_id,
            'role': role,
            'config': config or {},
            'start_time': datetime.now().isoformat(),
            'action_count': 0,
            'message_count': 0,
            'error_count': 0
        }
        
        # Open log file for this session
        log_file_path = self.log_dir / f"{anonymized_user_id}_session_{session_id[:8]}.jsonl"
        self.session_files[session_id] = open(log_file_path, 'a', encoding='utf-8')
        self.session_locks[session_id] = Lock()
        
        # Log session start event
        self.log_action(
            session_id=session_id,
            action_type='system_event',
            event_name='session_start',
            details={
                'role': role,
                'config': config or {}
            },
            metadata={}
        )
        
        logger.info(f"Started logging session {session_id} for user {anonymized_user_id}")
    
    def log_action(
        self,
        session_id: str,
        action_type: str,
        event_name: str,
        details: Dict[str, Any],
        metadata: Dict[str, Any] = None
    ):
        """
        Log a single user action.
        
        Args:
            session_id: Session identifier
            action_type: Type of action (game_action, socket_event, http_request, system_event)
            event_name: Specific event name
            details: Event-specific data
            metadata: Additional context metadata
        """
        if not settings.LOG_USER_ACTIONS or session_id not in self.session_files:
            return
        
        # Build log entry
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'session_id': session_id,
            'user_id': self.session_metadata.get(session_id, {}).get('user_id', session_id),
            'action_type': action_type,
            'event_name': event_name,
            'details': details,
            'metadata': metadata or {}
        }
        
        # Write to JSONL file (thread-safe)
        try:
            lock = self.session_locks.get(session_id)
            if lock:
                with lock:
                    file_handle = self.session_files[session_id]
                    file_handle.write(json.dumps(log_entry) + '\n')
                    file_handle.flush()  # Ensure immediate write
            
            # Update session metadata counters
            if session_id in self.session_metadata:
                self.session_metadata[session_id]['action_count'] += 1
                if action_type == 'game_action' and event_name == 'send_message':
                    self.session_metadata[session_id]['message_count'] += 1
                if details.get('success') is False or 'error' in details:
                    self.session_metadata[session_id]['error_count'] += 1
        
        except Exception as e:
            logger.error(f"Failed to log action for session {session_id}: {e}")
    
    def log_http_request(
        self,
        session_id: str,
        method: str,
        path: str,
        status_code: Optional[int] = None,
        duration_ms: Optional[float] = None
    ):
        """
        Log an HTTP request.
        
        Args:
            session_id: Session identifier
            method: HTTP method (GET, POST, etc.)
            path: Request path
            status_code: Response status code
            duration_ms: Request duration in milliseconds
        """
        self.log_action(
            session_id=session_id,
            action_type='http_request',
            event_name='http_request',
            details={
                'method': method,
                'path': path,
                'status_code': status_code,
                'duration_ms': duration_ms
            }
        )
    
    def log_socket_event(
        self,
        session_id: str,
        event_name: str,
        data: Any = None,
        success: bool = True,
        error: Optional[str] = None
    ):
        """
        Log a SocketIO event.
        
        Args:
            session_id: Session identifier
            event_name: Socket event name
            data: Event data
            success: Whether event was successful
            error: Error message if failed
        """
        # Sanitize data if needed (e.g., remove large payloads)
        sanitized_data = self._sanitize_data(data)
        
        self.log_action(
            session_id=session_id,
            action_type='socket_event',
            event_name=event_name,
            details={
                'data': sanitized_data,
                'success': success,
                'error': error
            }
        )
    
    def _sanitize_data(self, data: Any) -> Any:
        """
        Sanitize data before logging (remove sensitive or large data).
        
        Args:
            data: Raw data
            
        Returns:
            Sanitized data
        """
        if data is None:
            return None
        
        if isinstance(data, dict):
            sanitized = {}
            for key, value in data.items():
                # Skip large image data
                if key in ['piece_images', 'piece_images_b64', 'image_data']:
                    sanitized[key] = f"<{type(value).__name__} - omitted>"
                # Optionally exclude message content
                elif key == 'message' and not settings.LOG_MESSAGE_CONTENT:
                    sanitized[key] = f"<message length: {len(value) if isinstance(value, str) else 0}>"
                # Skip work area snapshots if configured
                elif key in ['work_area', 'target_area', 'work_area_snapshot'] and not settings.LOG_WORK_AREA_SNAPSHOTS:
                    sanitized[key] = "<grid data omitted>"
                else:
                    sanitized[key] = value
            return sanitized
        
        return data
    
    def end_session(
        self,
        session_id: str,
        summary_data: Optional[Dict[str, Any]] = None
    ):
        """
        Finalize session logging and write summary.
        
        Args:
            session_id: Session identifier
            summary_data: Additional summary data
        """
        if not settings.LOG_USER_ACTIONS or session_id not in self.session_files:
            return
        
        # Calculate session duration
        if session_id in self.session_metadata:
            metadata = self.session_metadata[session_id]
            start_time = datetime.fromisoformat(metadata['start_time'])
            end_time = datetime.now()
            duration_seconds = (end_time - start_time).total_seconds()
            
            # Log session end event
            self.log_action(
                session_id=session_id,
                action_type='system_event',
                event_name='session_end',
                details={
                    'duration_seconds': duration_seconds,
                    'action_count': metadata['action_count'],
                    'message_count': metadata['message_count'],
                    'error_count': metadata['error_count'],
                    'summary': summary_data or {}
                }
            )
            
            # Write to summary CSV
            self._write_session_summary(session_id, duration_seconds, summary_data)
        
        # Close file handle
        try:
            if session_id in self.session_files:
                self.session_files[session_id].close()
                del self.session_files[session_id]
            if session_id in self.session_locks:
                del self.session_locks[session_id]
            if session_id in self.session_metadata:
                del self.session_metadata[session_id]
            
            logger.info(f"Ended logging session {session_id}")
        
        except Exception as e:
            logger.error(f"Failed to close session {session_id}: {e}")
    
    def _write_session_summary(
        self,
        session_id: str,
        duration_seconds: float,
        summary_data: Optional[Dict[str, Any]]
    ):
        """
        Write session summary to CSV file.
        
        Args:
            session_id: Session identifier
            duration_seconds: Session duration
            summary_data: Additional summary data
        """
        csv_path = self.summary_dir / "session_summary.csv"
        
        metadata = self.session_metadata.get(session_id, {})
        config = metadata.get('config', {})
        
        # Prepare row data
        row = {
            'session_id': session_id,
            'user_id': metadata.get('user_id', ''),
            'role': metadata.get('role', ''),
            'start_time': metadata.get('start_time', ''),
            'duration_seconds': duration_seconds,
            'action_count': metadata.get('action_count', 0),
            'message_count': metadata.get('message_count', 0),
            'error_count': metadata.get('error_count', 0),
            'worker_mode': config.get('worker_mode', ''),
            'helper_mode': config.get('helper_mode', ''),
            'shared_view': config.get('shared_view', ''),
            'study_mode': config.get('study_mode', ''),
        }
        
        # Add summary data if provided
        if summary_data:
            row.update({
                'puzzles_completed': summary_data.get('puzzles_completed', 0),
                'puzzles_attempted': summary_data.get('puzzles_attempted', 0),
                'total_piece_placements': summary_data.get('total_piece_placements', 0),
            })
        
        # Check if file exists to determine if we need headers
        file_exists = csv_path.exists()
        
        try:
            with open(csv_path, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=row.keys())
                if not file_exists:
                    writer.writeheader()
                writer.writerow(row)
        
        except Exception as e:
            logger.error(f"Failed to write session summary: {e}")
    
    def cleanup_old_logs(self, retention_days: Optional[int] = None):
        """
        Delete log files older than retention period.
        
        Args:
            retention_days: Number of days to retain logs (defaults to settings)
        """
        retention_days = retention_days or settings.LOG_RETENTION_DAYS
        cutoff_date = datetime.now() - timedelta(days=retention_days)
        
        deleted_count = 0
        for log_file in self.log_dir.glob("*.jsonl"):
            if datetime.fromtimestamp(log_file.stat().st_mtime) < cutoff_date:
                try:
                    log_file.unlink()
                    deleted_count += 1
                except Exception as e:
                    logger.error(f"Failed to delete old log file {log_file}: {e}")
        
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old log files")


# Global user session logger instance
_user_session_logger = None
_logger_lock = Lock()


def get_user_session_logger() -> UserSessionLogger:
    """
    Get or create global user session logger (singleton).
    
    Returns:
        UserSessionLogger instance
    """
    global _user_session_logger
    
    if _user_session_logger is None:
        with _logger_lock:
            if _user_session_logger is None:
                _user_session_logger = UserSessionLogger()
    
    return _user_session_logger
