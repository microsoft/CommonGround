"""
Base agent class and LLM agent implementations for the puzzle task.
"""
import copy
import logging
import time
import json
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple

from .client import AIClient
from .state_serializer import GridStateSerializer, ActionParser
from .prompts import (
    WORKER_SYSTEM_PROMPT, WORKER_SYSTEM_PROMPT_UNCERTAINTY,FOLLOW_UP_PROMPT,
    HELPER_SYSTEM_PROMPT, HELPER_NON_SHARED_SYSTEM_PROMPT,
    get_worker_messages_content, get_helper_messages_content, get_helper_messages_non_shared_content,
    WORKER_INITIAL_PROMPT, WORKER_INITIAL_PROMPT_UNCERTAINTY, HELPER_INITIAL_PROMPT
)
from puzzle_constants import GRID_SIZE

# Import settings with fallback
try:
    from ..utils import settings
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from utils import settings


logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract base class for LLM agents."""
    
    def __init__(self, ai_client: AIClient, agent_id: str = "agent"):
        self.ai_client = ai_client
        self.agent_id = agent_id
        self.conversation_history: List[Dict[str, str]] = []
        self.action_history: List[Dict[str, Any]] = []
        self.serializer = GridStateSerializer()
        
    @abstractmethod
    def get_system_prompt(self) -> str:
        """Return the system prompt for this agent type."""
        pass
    
    @abstractmethod
    async def perceive_and_act(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Perceive the current state and decide on an action.
        
        Args:
            state: Dictionary containing game state information
            
        Returns:
            Dictionary with 'actions' and 'message' fields
        """
        pass
    
    def add_to_history(self, role: str, content: str):
        """Add message to conversation history."""
        self.conversation_history.append({
            "role": role,
            "content": content
        })
        # Keep only recent history to manage token limits
        if len(self.conversation_history) > settings.MAX_CONVERSATION_TURNS * 2:
            # Keep system prompt + recent messages
            self.conversation_history = (
                [self.conversation_history[0]] + 
                self.conversation_history[-(settings.MAX_CONVERSATION_TURNS * 2):]
            )
    
    def get_chat_history_text(self, max_messages: int = 6) -> str:
        """Format recent conversation history as text."""
        recent = self.conversation_history[-max_messages:] if max_messages else self.conversation_history
        lines = []
        for msg in recent:
            if msg["role"] == "system":
                continue
            speaker = "Helper" if msg["role"] == "assistant" else "Worker"
            lines.append(f"{speaker}: {msg['content']}")
        return "\n".join(lines)
    
    async def _call_llm(self, user_message_content, add_to_history: bool = True) -> str:
        """Call LLM with user message and conversation history."""
        # Build messages
        messages = [{"role": "system", "content": self.get_system_prompt()}]
        
        for msg in self.conversation_history:
            messages.append(msg)
        
        # Add current user message
        messages.append({"role": "user", "content": user_message_content})
        with open("last_message_sent.json", "w", encoding="utf-8") as f:
            json.dump(messages, f)
        
        # Call LLM
        try:
            response = await self.ai_client.get_chat_completion(
                messages=messages,
                max_tokens=settings.MAX_TOKENS_DEFAULT
            )
            
            # Update history
            if add_to_history:
                self.add_to_history("user", user_message_content)
            self.add_to_history("assistant", response)
            
            logger.info(f"{self.agent_id} LLM response: {response[:100]}...")
            return response
            
        except Exception as e:
            logger.error(f"{self.agent_id} LLM call failed: {e}")
            return f"ERROR: {str(e)}"
    
    def reset(self):
        """Reset agent state for new trial (soft reset - keeps conversation history)."""
        # Only clear action history, preserve conversation history across trials
        self.action_history.clear()
    
    def hard_reset(self):
        """Hard reset - clears all state including conversation history."""
        self.conversation_history.clear()
        self.action_history.clear()


class WorkerAgent(BaseAgent):
    """LLM-controlled Worker agent."""
    
    def __init__(self, ai_client: AIClient, uncertainty: bool = False):
        super().__init__(ai_client, agent_id="Worker")
        self.current_work_area = None
        self.staging_pieces = None
        self.piece_images = None
        self.uncertainty = uncertainty  # Whether the current puzzle uses the uncertainty condition
        
    def get_system_prompt(self) -> str:
        if self.uncertainty:
            return WORKER_SYSTEM_PROMPT_UNCERTAINTY
        return WORKER_SYSTEM_PROMPT
    
    async def perceive_and_act(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Worker perceives current grid and staging area, decides next action.
        
        Expected state format:
        {
            'work_area': List[List[Optional[int]]],
            'staging_pieces': List[Tuple[Any, int]],
            'piece_images': Dict[int, Image.Image],
            'chat_messages': List[str],  # Recent messages from Helper
            'is_first_action': bool
        }
        """
        logger.info(f"[DEBUG] WorkerAgent.perceive_and_act: ENTRY")
        self.current_work_area = state['work_area']
        self.staging_pieces = state['staging_pieces']
        self.piece_images = state['piece_images']
        logger.info(f"[DEBUG] WorkerAgent.perceive_and_act: State extracted")
        
        # Add recent chat messages to conversation history (from Helper)
        # These are messages the Worker should respond to
        # for msg in state.get('chat_messages', []):
        #     if msg and msg not in [h['content'] for h in self.conversation_history]:
        #         self.add_to_history("assistant", msg)  # Helper messages are "assistant" from worker's perspective
        
        # Serialize current state
        state_desc = self.serializer.serialize_full_state(
            work_area=self.current_work_area,
            staging_pieces=self.staging_pieces,
            piece_images=self.piece_images
        )

        pieces_img = self.serializer.serialize_piece_images_png(piece_images=self.piece_images)
        current_desc = self.serializer.serialize_grid_png(
            self.current_work_area,
            self.piece_images
        )

        # Get recent chat history
        # chat_history = self.get_chat_history_text(max_messages=6)

        # Add recent chat messages to conversation history (from Worker)
        # These are messages the Helper should respond to
        msgs = state.get('chat_messages', [])
        if msgs:
            self.add_to_history("user", msgs[-1])
        
        # Build prompt - use most recent helper message as context
        if state.get('is_first_action', False):
            context = WORKER_INITIAL_PROMPT_UNCERTAINTY if self.uncertainty else WORKER_INITIAL_PROMPT
            # Don't add to history - the instruction is passed via context
        elif msgs:
            # Use the most recent helper message as the instruction
            context = msgs[-1] + FOLLOW_UP_PROMPT if self.uncertainty else  ""
        else:
            context = ""
        
        content = get_worker_messages_content(
            state_description=current_desc,
            pieces_description=pieces_img,
            context=context
        )
        # print(context)
        
        
        # Simulate thinking time - no needed since API call is slow
        # think_time = random.uniform(
        #     settings.AGENT_THINK_TIME_MIN,
        #     settings.AGENT_THINK_TIME_MAX
        # )
        # await asyncio.sleep(think_time)
        
        # Call LLM
        logger.info(f"[DEBUG] WorkerAgent.perceive_and_act: About to call LLM")
        response = await self._call_llm(content, add_to_history=False)
        logger.info(f"[DEBUG] WorkerAgent.perceive_and_act: LLM call returned")

        # Parse response
        parsed = ActionParser.parse_llm_response(response)

        # Validate actions and filter out invalid ones
        valid_actions = []
        for action in parsed.get('actions', []):
            is_valid, error = self.validate_action(action)
            if is_valid:
                valid_actions.append(action)
            else:
                logger.warning(f"[VALIDATION] Invalid action rejected: {action} - {error}")
        parsed['actions'] = valid_actions

        # Log action
        self.action_history.append({
            'timestamp': time.time(),
            'state': state_desc,
            'response': response,
            'parsed': parsed
        })

        return parsed
    
    def validate_action(self, action: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Validate if action is legal in current state."""
        if action['action'] == 'place':
            piece_idx = action['piece']
            x, y = action['position']
            
            # Check if piece is available in staging
            available_pieces = [idx for _, idx in self.staging_pieces]
            if piece_idx not in available_pieces:
                return False, f"Piece #{piece_idx + 1} is not available in staging"
            
            # Check if position is valid
            if not (0 <= x < GRID_SIZE and 0 <= y < GRID_SIZE):
                return False, f"Position ({x}, {y}) is out of bounds"
            
            # Check if position is empty (warn but allow - will auto-replace)
            if self.current_work_area[y][x] is not None:
                logger.info(f"[VALIDATION] Position ({x}, {y}) occupied - will auto-replace")

            return True, None
            
        elif action['action'] == 'move':
            from_x, from_y = action['from']
            to_x, to_y = action['to']
            
            # Check if source has a piece
            if not (0 <= from_x < GRID_SIZE and 0 <= from_y < GRID_SIZE):
                return False, f"Source position ({from_x}, {from_y}) is out of bounds"
            
            if self.current_work_area[from_y][from_x] is None:
                return False, f"No piece at position ({from_x}, {from_y})"
            
            # Check if destination is valid and empty
            if not (0 <= to_x < GRID_SIZE and 0 <= to_y < GRID_SIZE):
                return False, f"Destination position ({to_x}, {to_y}) is out of bounds"
            
            if self.current_work_area[to_y][to_x] is not None:
                return False, f"Position ({to_x}, {to_y}) is already occupied"
            
            return True, None
        
        elif action['action'] == 'remove':
            x, y = action['position']

            # Check if position is valid and has a piece
            if not (0 <= x < GRID_SIZE and 0 <= y < GRID_SIZE):
                return False, f"Position ({x}, {y}) is out of bounds"
            
            if self.current_work_area[y][x] is None:
                return False, f"No piece at position ({x}, {y}) to remove"
            
            return True, None
        
        return False, f"Unknown action type: {action.get('action')}"
    
    def reset(self):
        """Reset agent state for new trial (soft reset - keeps conversation history)."""
        # Only clear action history, preserve conversation history across trials
        self.action_history.clear()
        # Reset puzzle-specific state
        self.current_work_area = None
        self.staging_pieces = None
        # Note: piece_images typically stays the same across puzzles


class HelperAgent(BaseAgent):
    """LLM-controlled Helper agent."""
    
    def __init__(self, ai_client: AIClient, shared_view: bool = True):
        super().__init__(ai_client, agent_id="Helper")
        self.target_area = None
        self.worker_area = None
        self.piece_images = None
        self.last_worker_area = None
        self.guidance_count = 0
        self.shared_view = shared_view
        
    def get_system_prompt(self) -> str:
        if self.shared_view:
            return HELPER_SYSTEM_PROMPT
        else:
            return HELPER_NON_SHARED_SYSTEM_PROMPT
    
    async def perceive_and_act(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Helper perceives target and current progress, provides guidance.
        
        Expected state format:
        {
            'target_area': List[List[Optional[int]]],
            'worker_area': List[List[Optional[int]]],
            'piece_images': Dict[int, Image.Image],
            'chat_messages': List[str],  # Recent messages from Worker
            'is_first_guidance': bool,
            'worker_action': Optional[Dict]  # Last worker action
        }
        """
        self.target_area = state['target_area']
        
        self.worker_area = state['worker_area']
        self.piece_images = state['piece_images']
        
        # Add recent chat messages to conversation history (from Worker)
        # These are messages the Helper should respond to
        msgs = state.get('chat_messages', [])
        if msgs:
            self.add_to_history("user", msgs[-1])
        # for msg in state.get('chat_messages', []):
        #     if msg and msg not in [h['content'] for h in self.conversation_history]:
        #         self.add_to_history("user", msg)  # Worker messages are "user" from helper's perspective
        
        # Serialize states
        target_desc = self.serializer.serialize_grid(
            self.target_area, 
            self.piece_images
        )
        
        target_img_b64 = self.serializer.serialize_grid_png(
            self.target_area, 
            self.piece_images,
            border_width=0
        )

        current_desc = self.serializer.serialize_grid(
            self.worker_area,
            self.piece_images
        )

        current_img_b64 = self.serializer.serialize_grid_png(
            self.worker_area,
            self.piece_images
        )

        diff_summary = self.serializer.compare_grids(
            self.worker_area,
            self.target_area,
            self.piece_images
        )

        # Build prompt
        if state.get('is_first_guidance', False):
            if self.shared_view:
                comparison = HELPER_INITIAL_PROMPT
                # Add just the worker's initial message (not the full instruction prompt)
                self.add_to_history("user", "I am ready for your instructions.")
            else:
                comparison = HELPER_NON_SHARED_SYSTEM_PROMPT
                self.add_to_history("user", "I am ready for your instructions.")
        else:
            comparison = ""
            if (self.last_worker_area != self.worker_area) and self.shared_view:
                comparison=comparison + f"\nExternal information: {diff_summary}. Compare this target pattern with current worker's pattern (Does it contain the right pieces in the right location?) and advice the worker for the next step."
                #comparison=comparison + f"\nCompare this target pattern with current worker's pattern (Does it contain the right pieces in the right location?) and advice the worker for the next step."
            elif self.shared_view:
                comparison=comparison + f"\nExternal information: {diff_summary}. Handle the last worker's response."
                #comparison=comparison + f"\nHandle the last worker's response."
            else:
                comparison=comparison + "\nHandle the last worker's response."


        if self.shared_view:
            content = get_helper_messages_content(
                current_state=current_img_b64,
                target_state=target_img_b64,
                comparison=comparison
            )
        else:
            content = get_helper_messages_non_shared_content(
                target_state=target_img_b64,
                comparison=comparison
            )
        
        # Simulate thinking time - not needed since API call is slow
        # think_time = random.uniform(
        #     settings.AGENT_THINK_TIME_MIN,
        #     settings.AGENT_THINK_TIME_MAX
        # )
        # await asyncio.sleep(think_time)
        
        # Call LLM
        response = await self._call_llm(content, add_to_history=False)
        
        # Parse response (Helper primarily sends messages)
        parsed = ActionParser.parse_llm_response(response)
        
        # If no explicit message found, use the whole response
        if not parsed['message']:
            parsed['message'] = response.strip()
        
        # Log guidance
        self.action_history.append({
            'timestamp': time.time(),
            'target': target_desc,
            'current': current_desc,
            'comparison': comparison,
            'response': response,
            'parsed': parsed
        })
        
        self.guidance_count += 1

        self.last_worker_area = copy.deepcopy(self.worker_area)
        
        return parsed
    
    def should_provide_guidance(self, worker_action_count: int) -> bool:
        """Determine if Helper should provide proactive guidance."""
        if not settings.HELPER_PROACTIVE:
            return False
        
        # Provide guidance every N worker actions
        return worker_action_count % settings.HELPER_GUIDANCE_FREQUENCY == 0
    
    def reset(self):
        """Reset agent state for new trial (soft reset - keeps conversation history)."""
        # Only clear action history, preserve conversation history across trials
        self.action_history.clear()
        # Reset last_worker_area for the new puzzle
        self.last_worker_area = None
        # Reset guidance count for the new puzzle
        self.guidance_count = 0
