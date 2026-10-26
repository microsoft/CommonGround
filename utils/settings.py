"""
Configuration settings for CommonGround Chat application.
Centralizes all environment variable handling and default values.
"""
import os
from typing import Optional
from dotenv import load_dotenv


class Settings:
    """Application configuration settings."""
    
    def __init__(self):
        # Load environment variables
        load_dotenv()
        
        # Validate required environment variables (only for chat app, not puzzle)
        # self._validate_required_env_vars()
        
        # Azure OpenAI Configuration
        self.OPENAI_SCOPE = os.environ.get("OPENAI_SCOPE", "")
        self.OPENAI_ENDPOINT = os.environ.get("OPENAI_ENDPOINT", "")
        self.OPENAI_GPT4_DEPLOYMENT = os.environ.get("OPENAI_GPT4_DEPLOYMENT", "")
        self.OPENAI_API_VERSION = os.environ.get("OPENAI_API_VERSION", "")
        # Optional API key. If set, it is used instead of Entra ID (az login).
        self.OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
        
        # Study Configuration
        self.STUDY_ID = os.environ.get("STUDY_ID", "123")
        # Default to utils/user_credentials.json in the same directory
        default_creds_path = os.path.join(os.path.dirname(__file__), "user_credentials.json")
        self.USER_CREDENTIALS_FILE = os.environ.get("USER_CREDENTIALS_FILE", default_creds_path)
        
        # File Paths
        self.LOGS_DIR = self._get_logs_directory()
        self.SYSTEM_PROMPTS_FILE = "system_prompts.json"
        self.DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "conversations.db")
        
        # Chat Configuration
        self.MAX_TOKENS_DEFAULT = 1500
        self.MAX_CONVERSATION_TURNS = 20
        
        # Logging Configuration
        self.LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
        # Anchor relative log paths to the app so writers and downloads agree.
        _log_dir_env = os.environ.get("LOG_DIR", "logs")
        _puzzle_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.LOG_DIR = _log_dir_env if os.path.isabs(_log_dir_env) else os.path.join(_puzzle_dir, _log_dir_env)
        self.LOG_LLM_INTERACTIONS = True
        
        # User Action Logging Configuration
        self.LOG_USER_ACTIONS = os.environ.get("LOG_USER_ACTIONS", "True").lower() == "true"
        self.LOG_MESSAGE_CONTENT = os.environ.get("LOG_MESSAGE_CONTENT", "True").lower() == "true"
        self.LOG_WORK_AREA_SNAPSHOTS = os.environ.get("LOG_WORK_AREA_SNAPSHOTS", "True").lower() == "true"
        self.ANONYMIZE_USER_IDS = os.environ.get("ANONYMIZE_USER_IDS", "True").lower() == "true"
        self.LOG_RETENTION_DAYS = int(os.environ.get("LOG_RETENTION_DAYS", "90"))
        
        # Agent Behavior Settings
        self.AGENT_THINK_TIME_MIN = float(os.environ.get("AGENT_THINK_TIME_MIN", "1.0"))
        self.AGENT_THINK_TIME_MAX = float(os.environ.get("AGENT_THINK_TIME_MAX", "3.0"))
        self.AGENT_MAX_RETRIES = int(os.environ.get("AGENT_MAX_RETRIES", "3"))
        
        # Worker Agent Settings
        self.WORKER_HELP_THRESHOLD = float(os.environ.get("WORKER_HELP_THRESHOLD", "0.3"))
        self.WORKER_EXPLORATION_RATE = float(os.environ.get("WORKER_EXPLORATION_RATE", "0.1"))
        
        # Helper Agent Settings
        self.HELPER_GUIDANCE_FREQUENCY = int(os.environ.get("HELPER_GUIDANCE_FREQUENCY", "3"))
        self.HELPER_PROACTIVE = os.environ.get("HELPER_PROACTIVE", "True").lower() == "true"
        
        # Experiment Settings
        self.TRIAL_TIMEOUT = int(os.environ.get("TRIAL_TIMEOUT", "300"))
        self.AUTO_START_TRIALS = os.environ.get("AUTO_START_TRIALS", "False").lower() == "true"
    
    def _validate_required_env_vars(self) -> None:
        """Validate that all required environment variables are set."""
        required_vars = [
            "OPENAI_SCOPE", 
            "OPENAI_ENDPOINT", 
            "OPENAI_GPT4_DEPLOYMENT", 
            "OPENAI_API_VERSION", 
            "STUDY_ID"
        ]
        
        missing_vars = [var for var in required_vars if not os.environ.get(var)]
        
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
    
    def _get_logs_directory(self) -> str:
        """Determine the appropriate logs directory path."""
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "conversation_logs"
        )


# Global settings instance
settings = Settings()
