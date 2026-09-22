"""
Integration module connecting LLM agents with the puzzle UI.
"""
import asyncio
import logging
import queue
from typing import Optional, Dict, Any
from datetime import datetime

from .client import get_ai_client
from .agents import WorkerAgent, HelperAgent
from .logger import get_trial_logger


logger = logging.getLogger(__name__)


class AgentController:
    """Controls LLM agents and interfaces with UI."""
    
    def __init__(self, worker_mode: str = "human", helper_mode: str = "human", shared_view: bool = True, uncertainty: bool = False):
        """
        Initialize agent controller.
        
        Args:
            worker_mode: "human" or "llm"
            helper_mode: "human" or "llm"
            shared_view: Whether helper can see worker's board
            uncertainty: Whether the current puzzle uses the uncertainty condition
        """
        self.worker_mode = worker_mode
        self.helper_mode = helper_mode
        self.shared_view = shared_view
        self.uncertainty = uncertainty
        
        self.ai_client = get_ai_client() if (worker_mode == "llm" or helper_mode == "llm") else None
        self.worker_agent = WorkerAgent(self.ai_client, uncertainty=uncertainty) if worker_mode == "llm" else None
        self.helper_agent = HelperAgent(self.ai_client, shared_view=shared_view) if helper_mode == "llm" else None
        
        self.trial_logger = get_trial_logger()
        self.worker_action_count = 0
        self.helper_guidance_count = 0
        
    def start_trial(self, trial_id: str, config: Dict[str, Any]):
        """Start a new trial."""
        self.trial_logger.start_trial(trial_id, config)
        self.worker_action_count = 0
        self.helper_guidance_count = 0

        # Update shared_view setting if it changed (e.g., switching between shared/non-shared puzzles)
        if 'shared_view' in config:
            new_shared_view = config['shared_view']
            if new_shared_view != self.shared_view:
                print(f"[DEBUG] AgentController: Updating shared_view from {self.shared_view} to {new_shared_view}")
                self.shared_view = new_shared_view
                # Update helper agent's shared_view if it exists
                if self.helper_agent:
                    self.helper_agent.shared_view = new_shared_view
                    print(f"[DEBUG] Updated HelperAgent.shared_view to {new_shared_view}")

        # Update uncertainty setting based on the puzzle condition (e.g., switching
        # between control and uncertainty puzzles). Drives the Worker's prompt selection.
        if 'condition' in config:
            new_uncertainty = config['condition'] == 'uncertainty'
            if new_uncertainty != self.uncertainty:
                print(f"[DEBUG] AgentController: Updating uncertainty from {self.uncertainty} to {new_uncertainty}")
                self.uncertainty = new_uncertainty
                # Update worker agent's uncertainty flag if it exists
                if self.worker_agent:
                    self.worker_agent.uncertainty = new_uncertainty
                    print(f"[DEBUG] Updated WorkerAgent.uncertainty to {new_uncertainty}")

        if self.worker_agent:
            self.worker_agent.hard_reset()
        if self.helper_agent:
            self.helper_agent.hard_reset()
        
        logger.info(f"Started trial {trial_id} with worker={self.worker_mode}, helper={self.helper_mode}")
    
    def end_trial(self, success: bool, completion_time: float = None):
        """End current trial."""
        self.trial_logger.end_trial(success, completion_time)
        logger.info(f"Ended trial: success={success}, time={completion_time}")
    
    async def get_worker_action(
        self,
        work_area,
        staging_pieces,
        piece_images,
        recent_messages
    ) -> Optional[Dict[str, Any]]:
        """
        Get next action from Worker (LLM or wait for human).
        
        Returns dict with 'actions' and 'message' or None if human mode.
        """
        if self.worker_mode != "llm":
            self.worker_action_count += 1
            return None
        
        state = {
            'work_area': work_area,
            'staging_pieces': staging_pieces,
            'piece_images': piece_images,
            'chat_messages': recent_messages,
            'is_first_action': self.worker_action_count == 0
        }
        
        try:
            logger.info(f"[DEBUG] get_worker_action: About to call worker_agent.perceive_and_act()")
            result = await self.worker_agent.perceive_and_act(state)
            logger.info(f"[DEBUG] get_worker_action: worker_agent.perceive_and_act() returned")
            self.worker_action_count += 1
            
            # Log to trial logger
            if result['actions']:
                for action in result['actions']:
                    self.trial_logger.log_action("Worker", action, True)
            if result['message']:
                self.trial_logger.log_message("Worker", "Helper", result['message'])
            
            return result
            
        except Exception as e:
            logger.error(f"Worker agent error: {e}")
            self.trial_logger.log_action("Worker", {'error': str(e)}, False, str(e))
            return None
    
    async def get_helper_guidance(
        self,
        target_area,
        worker_area,
        piece_images,
        recent_messages,
        worker_action: Optional[Dict] = None
    ) -> Optional[str]:
        """
        Get guidance from Helper (LLM or wait for human).
        
        Returns message string or None if human mode.
        """
        if self.helper_mode != "llm":
            self.helper_guidance_count += 1
            return None
        
        # Check if helper should provide guidance
        if worker_action is None and self.helper_agent:
            if not self.helper_agent.should_provide_guidance(self.worker_action_count):
                return None
        
        state = {
            'target_area': target_area,
            'worker_area': worker_area,
            'piece_images': piece_images,
            'chat_messages': recent_messages,
            'is_first_guidance': self.helper_guidance_count == 0,
            'worker_action': worker_action
        }
        
        try:
            result = await self.helper_agent.perceive_and_act(state)
            self.helper_guidance_count += 1
            
            # Log to trial logger
            if result['message']:
                self.trial_logger.log_message("Helper", "Worker", result['message'])
                return result['message']
            
            return None
            
        except Exception as e:
            logger.error(f"Helper agent error: {e}")
            return None
    
    def validate_worker_action(self, action: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """Validate a worker action."""
        if self.worker_agent:
            return self.worker_agent.validate_action(action)
        return True, None


class AsyncExecutor:
    """Helper to execute async functions from sync context."""
    
    def __init__(self):
        self.loop = None
        self.thread = None
        
    def run_async(self, coro):
        """Run async coroutine and return result."""
        return asyncio.run(coro)
    
    def run_async_in_background(self, coro, callback):
        """Run async coroutine in background and call callback with result."""
        def _run():
            try:
                result = asyncio.run(coro)
                callback(result)
            except Exception as e:
                logger.error(f"Background async error: {e}")
                callback(None)
        
        import threading
        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
