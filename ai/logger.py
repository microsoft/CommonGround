"""
Logging utilities for LLM agent interactions and trial data.
"""
import json
import csv
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

# Import settings with fallback
try:
    from ..utils import settings
except ImportError:
    import sys
    from pathlib import Path as P
    sys.path.insert(0, str(P(__file__).parent.parent))
    from utils import settings


# Setup logger
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


class TrialLogger:
    """Logs detailed trial data including LLM interactions."""
    
    def __init__(self, log_dir: str = None):
        self.log_dir = Path(log_dir or settings.LOG_DIR)
        self.log_dir.mkdir(exist_ok=True)
        
        self.current_trial_id = None
        self.trial_start_time = None
        self.trial_data = {}
        
    def start_trial(self, trial_id: str, config: Dict[str, Any]):
        """Start logging a new trial."""
        self.current_trial_id = trial_id
        self.trial_start_time = datetime.now()
        
        self.trial_data = {
            'trial_id': trial_id,
            'start_time': self.trial_start_time.isoformat(),
            'config': config,
            'user_id': config.get('user_id'),
            'prolific_pid': config.get('prolific_pid'),
            'study_id': config.get('study_id'),
            'user_function': config.get('user_function'),
            'session_id': config.get('session_id'),
            'actions': [],
            'messages': [],
            'llm_interactions': [],
            'events': []
        }
        
    def log_action(self, agent: str, action: Dict[str, Any], success: bool, error: str = None):
        """Log an agent action."""
        if not self.current_trial_id:
            return
        
        self.trial_data['actions'].append({
            'timestamp': datetime.now().isoformat(),
            'agent': agent,
            'action': action,
            'success': success,
            'error': error
        })
    
    def log_message(self, sender: str, receiver: str, content: str):
        """Log a chat message."""
        if not self.current_trial_id:
            return
        
        self.trial_data['messages'].append({
            'timestamp': datetime.now().isoformat(),
            'sender': sender,
            'receiver': receiver,
            'content': content
        })
    
    def log_llm_interaction(
        self, 
        agent: str, 
        prompt: str, 
        response: str,
        parsed_output: Dict[str, Any] = None
    ):
        """Log an LLM API call."""
        if not self.current_trial_id or not settings.LOG_LLM_INTERACTIONS:
            return
        
        self.trial_data['llm_interactions'].append({
            'timestamp': datetime.now().isoformat(),
            'agent': agent,
            'prompt': prompt,
            'response': response,
            'parsed_output': parsed_output
        })
    
    def log_event(self, event_type: str, details: Dict[str, Any]):
        """Log a general event."""
        if not self.current_trial_id:
            return
        
        self.trial_data['events'].append({
            'timestamp': datetime.now().isoformat(),
            'event_type': event_type,
            'details': details
        })
    
    def end_trial(self, success: bool, completion_time: float = None):
        """End current trial and save data."""
        if not self.current_trial_id:
            return
        
        end_time = datetime.now()
        duration = (end_time - self.trial_start_time).total_seconds()
        
        self.trial_data['end_time'] = end_time.isoformat()
        self.trial_data['duration_seconds'] = completion_time or duration
        self.trial_data['success'] = success
        
        # Save to JSON file
        json_path = self.log_dir / f"{self.current_trial_id}_detailed.json"
        with open(json_path, 'w') as f:
            json.dump(self.trial_data, f, indent=2)
        
        # Append summary to CSV
        self._append_to_summary_csv()
        
        # Reset
        self.current_trial_id = None
        self.trial_data = {}
    
    def _append_to_summary_csv(self):
        """Append trial summary to CSV file."""
        csv_path = self.log_dir / "trial_summary.csv"
        
        # Prepare row data
        config = self.trial_data['config']
        row = {
            'trial_id': self.trial_data['trial_id'],
            'user_id': self.trial_data.get('user_id', ''),
            'prolific_pid': self.trial_data.get('prolific_pid', ''),
            'study_id': self.trial_data.get('study_id', ''),
            'user_function': self.trial_data.get('user_function', ''),
            'session_id': self.trial_data.get('session_id', ''),
            'start_time': self.trial_data['start_time'],
            'duration_seconds': self.trial_data['duration_seconds'],
            'success': self.trial_data['success'],
            'puzzle_number': config.get('puzzle_number', ''),
            'worker_mode': config.get('worker_mode', 'unknown'),
            'helper_mode': config.get('helper_mode', 'unknown'),
            'feedback_mode': config.get('feedback_mode', 'unknown'),
            'shared_view': config.get('shared_view', ''),
            'num_actions': len(self.trial_data['actions']),
            'num_messages': len(self.trial_data['messages']),
            'num_llm_calls': len(self.trial_data['llm_interactions'])
        }
        
        # Check if file exists to determine if we need headers
        file_exists = csv_path.exists()
        
        with open(csv_path, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=row.keys())
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)


class AgentLogger:
    """Logger wrapper for individual agents."""
    
    def __init__(self, agent_name: str, trial_logger: TrialLogger):
        self.agent_name = agent_name
        self.trial_logger = trial_logger
        self.logger = logging.getLogger(f"agent.{agent_name}")
    
    def info(self, message: str):
        """Log info message."""
        self.logger.info(message)
    
    def error(self, message: str):
        """Log error message."""
        self.logger.error(message)
    
    def log_action(self, action: Dict[str, Any], success: bool, error: str = None):
        """Log agent action to trial logger."""
        self.trial_logger.log_action(self.agent_name, action, success, error)
    
    def log_llm_call(self, prompt: str, response: str, parsed: Dict[str, Any] = None):
        """Log LLM interaction to trial logger."""
        self.trial_logger.log_llm_interaction(
            self.agent_name, prompt, response, parsed
        )


# Global trial logger instance
_trial_logger = None

def get_trial_logger() -> TrialLogger:
    """Get or create global trial logger."""
    global _trial_logger
    if _trial_logger is None:
        _trial_logger = TrialLogger()
    return _trial_logger
