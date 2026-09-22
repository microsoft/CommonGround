"""
Authentication and user management for CommonGround Chat.
Handles user credential validation and session management.
"""
import json
import logging
import os
from typing import Dict, Optional, NamedTuple
from dataclasses import dataclass

# Get the default credentials file path
DEFAULT_CREDENTIALS_PATH = os.path.join(os.path.dirname(__file__), "user_credentials.json")


logger = logging.getLogger(__name__)


class ValidationResult(NamedTuple):
    """Result of user credential validation."""
    valid: bool
    error: Optional[str] = None
    user_data: Optional[dict] = None


@dataclass
class AuthInfo:
    """Authentication information for a logged-in user."""
    user_id: str
    study_id: str
    token: str
    user_data: dict
    prolific_pid: str = ""
    session_id: str = ""


class AuthManager:
    """Manages user authentication and authorization."""
    
    def __init__(self, credentials_file: str = None):
        self.credentials_file = credentials_file or DEFAULT_CREDENTIALS_PATH
        self._credentials_cache = None
    
    def load_user_credentials(self) -> Optional[Dict]:
        """Load user credentials from JSON file with caching."""
        if self._credentials_cache is not None:
            return self._credentials_cache
        
        try:
            with open(self.credentials_file, 'r', encoding='utf-8') as f:
                self._credentials_cache = json.load(f)
                logger.info(f"Loaded user credentials from {self.credentials_file}")
                return self._credentials_cache
                
        except FileNotFoundError:
            logger.error(f"User credentials file not found: {self.credentials_file}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in credentials file: {e}")
            return None
        except Exception as e:
            logger.error(f"Error loading user credentials: {e}")
            return None
    
    def validate_user_credentials(
        self, 
        user_id: str, 
        token: str, 
        study_id: str = None
    ) -> ValidationResult:
        """Validate user credentials against the stored credentials.
        
        Args:
            user_id: The user ID to validate
            token: The access token to validate
            study_id: Optional study ID (for informational purposes only)
        """
        credentials = self.load_user_credentials()
        
        if credentials is None:
            return ValidationResult(valid=False, error="Could not load user credentials")
        
        # Check if user exists
        users = credentials.get("users", {})
        if user_id not in users:
            logger.warning(f"User not found: {user_id}")
            return ValidationResult(valid=False, error="User not found")
        
        user_data = users[user_id]
        
        # Check token
        if token != user_data.get("token"):
            logger.warning(f"Invalid token for user: {user_id}")
            return ValidationResult(valid=False, error="Invalid token")
        
        logger.info(f"User authenticated successfully: {user_id} (study_id: {study_id or 'not provided'})")
        return ValidationResult(valid=True, user_data=user_data)
    
    def is_admin_user(self, user_data: dict) -> bool:
        """Check if user has admin privileges."""
        return user_data.get("role") == "admin"
    
    def get_user_system_prompt(self, user_data: dict) -> Optional[str]:
        """Get the assigned system prompt for a user. Returns None for admin users."""
        if self.is_admin_user(user_data):
            return None  # Admins can choose their own prompt
        return user_data.get("system_prompt")
    
    def create_auth_info(
        self,
        user_id: str,
        token: str,
        study_id: str,
        prolific_pid: str = "",
        session_id: str = ""
    ) -> Optional[AuthInfo]:
        """Create authentication info after validating credentials."""
        validation = self.validate_user_credentials(user_id, token, study_id)
        
        if not validation.valid:
            return None
        
        return AuthInfo(
            user_id=user_id,
            study_id=study_id,
            token=token,
            user_data=validation.user_data,
            prolific_pid=prolific_pid,
            session_id=session_id
        )
    
    def refresh_credentials_cache(self) -> None:
        """Clear the credentials cache to force reload on next access."""
        self._credentials_cache = None
        logger.info("Credentials cache cleared")


# Global auth manager instance
auth_manager = AuthManager()
