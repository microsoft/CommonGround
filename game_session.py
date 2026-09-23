"""
Game session management for puzzle collaboration task.
Contains GameSession class and session lookup helpers.
"""
import time
import uuid
import io
import base64
import os
import json
from datetime import datetime
from typing import Optional, Tuple
from PIL import Image
from flask import session, request

from puzzle_constants import (
    GRID_SIZE, PIECE_SIZE, NUM_PIECES,
    TILE_PATTERNS, generate_pattern_block, PALETTE_TO_TILE_INDEX
)

# Import AI agent if available
try:
    from ai import AgentController, get_async_executor
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False

# Import user session logger
try:
    from web_logger import get_user_session_logger
    LOGGING_AVAILABLE = True
except ImportError:
    LOGGING_AVAILABLE = False

# Game sessions: each user gets their own isolated game session
# Key: user_session_id (UUID stored in Flask session)
# Value: GameSession instance
user_sessions = {}

# Escape hatch for the require_complete condition: after this many seconds on a
# gated puzzle, advancing is auto-unlocked so a participant can never get stuck
# (e.g. if the AI worker can't be guided to place every piece). Overridable
# per-puzzle via the optional "require_complete_timeout" field.
DEFAULT_REQUIRE_COMPLETE_TIMEOUT = 300  # 5 minutes


class GameSession:
    """Represents a single puzzle game session."""
    
    def __init__(self, session_id, worker_mode='human', helper_mode='human', shared_view=True):
        self.session_id = session_id
        self.worker_mode = worker_mode  # 'human' or 'llm'
        self.helper_mode = helper_mode  # 'human' or 'llm'
        self.shared_view = shared_view  # Whether helper can see worker's progress
        self.uncertainty = False  # Whether the current puzzle uses the uncertainty condition
        self.require_complete = False  # If True, can only advance once all target pieces are correctly placed
        self.require_complete_timeout = DEFAULT_REQUIRE_COMPLETE_TIMEOUT  # Auto-unlock the gate after this many seconds
        self.worker_sid = None
        self.helper_sid = None
        
        # User identification (populated when user joins)
        self.user_id = None
        self.prolific_pid = None
        self.study_id = None
        self.user_function = None  # 'worker' or 'helper'
        
        # Track active worker loop with unique ID to prevent multiple loops
        self.worker_loop_id = 0  # Incremented each time a new loop should start
        self.worker_loop_running = False  # True when a loop is actively executing
        self.transitioning_to_next_trial = False  # Flag to prevent multiple next_trial calls
        
        # Load predefined puzzles from config
        self.puzzles = self._load_puzzles()
        self.current_puzzle_index = 0
        
        # Game state
        self.work_area = [[None for _ in range(GRID_SIZE)] for _ in range(GRID_SIZE)]
        self.target_area = [[None for _ in range(GRID_SIZE)] for _ in range(GRID_SIZE)]
        # staging_pieces format: list of (canvas_id, piece_index) tuples for AI compatibility
        self.staging_pieces = [(i, i) for i in range(NUM_PIECES)]  # (canvas_id, piece_idx)
        self.pieces_in_work_area = set()
        self.last_placed_piece = None
        self.waiting_for_helper = False
        
        # Trial tracking
        self.trial_active = False
        self.start_time = None
        self.current_puzzle_number = None
        
        # Chat history
        self.chat_history = []
        
        # Piece images (stored as base64)
        self.piece_images_b64 = {}
        self._generate_piece_images()
        
        # AI agent if LLM mode
        self.agent_controller = None
        self.async_executor = None
        if (worker_mode == 'llm' or helper_mode == 'llm') and AI_AVAILABLE:
            print(f"[DEBUG] Initializing AI agent controller (worker={worker_mode}, helper={helper_mode})...")
            self.agent_controller = AgentController(
                worker_mode=worker_mode,
                helper_mode=helper_mode
            )
            self.async_executor = get_async_executor()
            print(f"[DEBUG] AI agent controller initialized successfully")
        elif (worker_mode == 'llm' or helper_mode == 'llm') and not AI_AVAILABLE:
            print(f"[WARNING] LLM mode requested but AI module not available!")
        else:
            print(f"[DEBUG] Using human-only mode (worker={worker_mode}, helper={helper_mode})")
        
        # User session logger
        self.session_logger = None
        if LOGGING_AVAILABLE:
            self.session_logger = get_user_session_logger()
            # Will be initialized with user info when user joins
    
    def _load_puzzles(self):
        """Load puzzles from utils/puzzles.json"""
        config_path = os.path.join(os.path.dirname(__file__), 'utils', 'puzzles.json')
        try:
            with open(config_path, 'r') as f:
                puzzles = json.load(f)
            print(f"[DEBUG] Loaded {len(puzzles)} puzzles from {config_path}")
            return puzzles
        except Exception as e:
            print(f"[ERROR] Failed to load puzzles from {config_path}: {e}")
            return []
    
    def _generate_piece_images(self):
        """Generate all puzzle piece images as base64."""
        for i in range(NUM_PIECES):
            img, color, pattern = generate_pattern_block(size=PIECE_SIZE - 10, piece_idx=i)
            
            # Convert PIL image to base64
            buffered = io.BytesIO()
            img.save(buffered, format="PNG")
            img_str = base64.b64encode(buffered.getvalue()).decode()
            self.piece_images_b64[i] = {
                'data': img_str,
                'color': color,
                'pattern': pattern
            }
    
    def _get_current_metadata(self):
        """Helper to extract current session metadata for logging."""
        return {
            'role': 'worker' if self.worker_mode == 'human' else 'helper',
            'worker_mode': self.worker_mode,
            'helper_mode': self.helper_mode,
            'shared_view': self.shared_view,
            'require_complete': self.require_complete,
            'current_puzzle': self.current_puzzle_number,
            'puzzle_index': self.current_puzzle_index,
            'trial_active': self.trial_active,
            'waiting_for_helper': self.waiting_for_helper,
            'pieces_in_work_area': len(self.pieces_in_work_area)
        }
    
    def start_trial(self, puzzle_index=None):
        """Start a trial using a predefined puzzle configuration."""
        # Use specified index or current index
        if puzzle_index is not None:
            self.current_puzzle_index = puzzle_index
        
        # Check if we have puzzles and valid index
        if not self.puzzles or self.current_puzzle_index >= len(self.puzzles):
            return None, "No more puzzles available"
        
        # Increment loop ID to invalidate any existing loops
        self.worker_loop_id += 1
        print(f"[DEBUG] Incremented worker_loop_id to {self.worker_loop_id} - old loops will exit")
        print(f"[DEBUG] start_trial() before setup: trial_active={self.trial_active}")
        
        puzzle = self.puzzles[self.current_puzzle_index]
        
        # Clear areas
        self.work_area = [[None for _ in range(GRID_SIZE)] for _ in range(GRID_SIZE)]
        self.target_area = [[None for _ in range(GRID_SIZE)] for _ in range(GRID_SIZE)]
        self.pieces_in_work_area = set()
        self.last_placed_piece = None
        self.waiting_for_helper = False
        
        # Set up target area from puzzle config
        # tiles contains palette indices (0-23), need to convert to tile indices (0-15)
        palette_indices = puzzle['tiles']
        positions = puzzle['positions']
        
        for palette_idx, position in zip(palette_indices, positions):
            x, y = position
            # Convert palette index to tile index
            tile_idx = PALETTE_TO_TILE_INDEX.get(palette_idx, palette_idx)
            self.target_area[y][x] = tile_idx
            print(f"[DEBUG] Placing palette_idx={palette_idx} -> tile_idx={tile_idx} at position ({x}, {y})")
        
        # Update shared view setting based on puzzle group
        puzzle_group = puzzle.get('group', '')
        if 'Non-shared' in puzzle_group:
            self.shared_view = False
        else:
            self.shared_view = True

        # Experimental condition for this puzzle ('uncertainty' or 'control').
        # Drives the Worker agent's prompt selection (uncertainty vs. standard).
        puzzle_condition = puzzle.get('condition', '')
        self.uncertainty = puzzle_condition == 'uncertainty'

        # If True, advancing to the next puzzle is only allowed once all target
        # pieces are correctly placed on the board (extra pieces are allowed).
        # Independent of shared/non-shared view.
        self.require_complete = bool(puzzle.get('require_complete', False))
        # Escape hatch: auto-unlock the gate after this many seconds so a
        # participant can never get permanently stuck on a gated puzzle.
        self.require_complete_timeout = int(
            puzzle.get('require_complete_timeout', DEFAULT_REQUIRE_COMPLETE_TIMEOUT)
        )
        self.trial_active = True
        self.start_time = time.time()
        self.current_puzzle_number = puzzle['puzzle_number']
        print(f"[DEBUG] start_trial() after setup: trial_active={self.trial_active}, worker_loop_id={self.worker_loop_id}")
        
        # Initialize AI agent if LLM mode
        if self.agent_controller:
            trial_id = f"puzzle_{self.current_puzzle_number}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            config = {
                'worker_mode': self.worker_mode,
                'helper_mode': self.helper_mode,
                'feedback_mode': 'immediate',
                'puzzle_number': self.current_puzzle_number,
                'shared_view': self.shared_view,
                'condition': puzzle_condition,
                'require_complete': self.require_complete,
                'user_id': self.user_id,
                'prolific_pid': self.prolific_pid,
                'study_id': self.study_id,
                'user_function': self.user_function,
                'session_id': self.session_id
            }
            self.agent_controller.start_trial(trial_id, config)
        
        num_pieces = len(palette_indices)
        print(f"[DEBUG] Started puzzle {self.current_puzzle_number} ({puzzle_group}) with {num_pieces} pieces, shared_view={self.shared_view}")
        
        # Log trial start
        if self.session_logger:
            self.session_logger.log_action(
                session_id=self.session_id,
                action_type='game_action',
                event_name='start_trial',
                details={
                    'puzzle_number': self.current_puzzle_number,
                    'user_id': self.user_id,
                    'prolific_pid': self.prolific_pid,
                    'study_id': self.study_id,
                    'user_function': self.user_function,
                    'puzzle_index': self.current_puzzle_index,
                    'puzzle_group': puzzle_group,
                    'num_pieces': num_pieces,
                    'shared_view': self.shared_view,
                    'require_complete': self.require_complete,
                    'target_area': self.target_area
                },
                metadata=self._get_current_metadata()
            )
        
        return num_pieces, puzzle
    
    def next_trial(self):
        """Move to the next trial."""
        # Log navigation to next trial
        if self.session_logger:
            self.session_logger.log_action(
                session_id=self.session_id,
                action_type='game_action',
                event_name='next_trial',
                details={
                    'from_puzzle_index': self.current_puzzle_index,
                    'to_puzzle_index': self.current_puzzle_index + 1
                },
                metadata=self._get_current_metadata()
            )
        
        self.current_puzzle_index += 1
        return self.start_trial()
    
    def get_trial_info(self):
        """Get information about the current and remaining trials."""
        if not self.puzzles:
            return {
                'current': 0,
                'total': 0,
                'has_next': False,
                'current_puzzle': None
            }
        
        return {
            'current': self.current_puzzle_index + 1,
            'total': len(self.puzzles),
            'has_next': self.current_puzzle_index < len(self.puzzles) - 1,
            'current_puzzle': self.puzzles[self.current_puzzle_index] if self.current_puzzle_index < len(self.puzzles) else None
        }
    
    def all_targets_placed(self):
        """Return True if every target cell holds the correct piece.

        Extra pieces placed in non-target cells are allowed ("at least all
        correct pieces are on the board").
        """
        for y in range(GRID_SIZE):
            for x in range(GRID_SIZE):
                target = self.target_area[y][x]
                if target is not None and self.work_area[y][x] != target:
                    return False
        return True
    
    def can_advance(self):
        """Whether advancing to the next puzzle is currently allowed.

        Always True unless this puzzle sets ``require_complete``, in which case
        all target pieces must be correctly placed first. As an escape hatch,
        advancing is also auto-unlocked once ``require_complete_timeout`` seconds
        have elapsed, so a participant can never get permanently stuck.
        """
        if not self.require_complete:
            return True
        if self.all_targets_placed():
            return True
        return self.require_complete_timed_out()

    def require_complete_timed_out(self):
        """True if the gated puzzle has exceeded its completion timeout."""
        if not self.require_complete or self.start_time is None:
            return False
        return (time.time() - self.start_time) >= self.require_complete_timeout
    
    def place_piece(self, piece_idx, x, y):
        """Place a piece on the work area."""
        # Log attempt
        if self.session_logger:
            self.session_logger.log_action(
                session_id=self.session_id,
                action_type='game_action',
                event_name='place_piece_attempt',
                details={
                    'piece_idx': piece_idx,
                    'position': {'x': x, 'y': y}
                },
                metadata=self._get_current_metadata()
            )
        
        # Check if waiting for helper (only for human helper mode)
        if self.waiting_for_helper and self.helper_mode == 'human':
            if self.session_logger:
                self.session_logger.log_action(
                    session_id=self.session_id,
                    action_type='game_action',
                    event_name='place_piece_blocked',
                    details={'piece_idx': piece_idx, 'position': {'x': x, 'y': y}, 'reason': 'waiting_for_helper'},
                    metadata=self._get_current_metadata()
                )
            return False, "Please wait for helper's response"
        
        # Check turn restriction (only for human helper mode)
        if self.helper_mode == 'human' and self.last_placed_piece is not None and piece_idx not in self.pieces_in_work_area:
            if self.session_logger:
                self.session_logger.log_action(
                    session_id=self.session_id,
                    action_type='game_action',
                    event_name='place_piece_blocked',
                    details={'piece_idx': piece_idx, 'position': {'x': x, 'y': y}, 'reason': 'turn_restriction'},
                    metadata=self._get_current_metadata()
                )
            return False, "Can only place one new piece per turn"

        # Auto-remove existing piece if cell is occupied (replacement)
        existing_piece = self.work_area[y][x]
        if existing_piece is not None:
            if existing_piece == piece_idx:
                # No-op: placing same piece in same position
                print(f"[DEBUG] No-op: piece {piece_idx} already at ({x},{y})")
                if self.session_logger:
                    self.session_logger.log_action(
                        session_id=self.session_id,
                        action_type='game_action',
                        event_name='place_piece_noop',
                        details={
                            'piece_idx': piece_idx,
                            'position': {'x': x, 'y': y},
                            'reason': 'same_piece_same_position'
                        },
                        metadata=self._get_current_metadata()
                    )
                return True, "Piece already in that position"
            print(f"[DEBUG] Auto-removing piece {existing_piece} from ({x},{y}) for replacement with {piece_idx}")
            self.pieces_in_work_area.discard(existing_piece)
            if self.session_logger:
                self.session_logger.log_action(
                    session_id=self.session_id,
                    action_type='game_action',
                    event_name='auto_remove_for_replace',
                    details={
                        'removed_piece_idx': existing_piece,
                        'position': {'x': x, 'y': y},
                        'new_piece_idx': piece_idx
                    },
                    metadata=self._get_current_metadata()
                )

        # Mark as placed
        if piece_idx not in self.pieces_in_work_area:
            self.last_placed_piece = piece_idx
            self.pieces_in_work_area.add(piece_idx)

        # Place piece
        self.work_area[y][x] = piece_idx
        
        # Only wait for helper response in human mode
        if self.helper_mode == 'human':
            self.waiting_for_helper = True
        
        # Log successful placement
        trial_complete = self.trial_active and self.work_area == self.target_area
        if self.session_logger:
            self.session_logger.log_action(
                session_id=self.session_id,
                action_type='game_action',
                event_name='place_piece_success',
                details={
                    'piece_idx': piece_idx,
                    'position': {'x': x, 'y': y},
                    'work_area_snapshot': self.work_area if trial_complete else None,
                    'trial_complete': trial_complete,
                    'trial_elapsed': time.time() - self.start_time if self.start_time else None
                },
                metadata=self._get_current_metadata()
            )
        
        if self.helper_mode == 'llm':
            return True, "Piece placed. Ask helper for guidance in chat."
        else:
            return True, "Piece placed. Send message to helper."
    
    def move_piece(self, from_x, from_y, to_x, to_y):
        """Move a piece within the work area."""
        # Log attempt
        if self.session_logger:
            self.session_logger.log_action(
                session_id=self.session_id,
                action_type='game_action',
                event_name='move_piece_attempt',
                details={
                    'from': {'x': from_x, 'y': from_y},
                    'to': {'x': to_x, 'y': to_y}
                },
                metadata=self._get_current_metadata()
            )
        
        # Only block for human helper mode
        if self.waiting_for_helper and self.helper_mode == 'human':
            if self.session_logger:
                self.session_logger.log_action(
                    session_id=self.session_id,
                    action_type='game_action',
                    event_name='move_piece_blocked',
                    details={'from': {'x': from_x, 'y': from_y}, 'to': {'x': to_x, 'y': to_y}, 'reason': 'waiting_for_helper'},
                    metadata=self._get_current_metadata()
                )
            return False, "Please wait for helper's response"
        
        piece_idx = self.work_area[from_y][from_x]
        if piece_idx is None:
            if self.session_logger:
                self.session_logger.log_action(
                    session_id=self.session_id,
                    action_type='game_action',
                    event_name='move_piece_failed',
                    details={'from': {'x': from_x, 'y': from_y}, 'to': {'x': to_x, 'y': to_y}, 'error': 'no_piece_at_source'},
                    metadata=self._get_current_metadata()
                )
            return False, "No piece at source position"
        
        self.work_area[from_y][from_x] = None
        self.work_area[to_y][to_x] = piece_idx
        
        # Log success
        if self.session_logger:
            self.session_logger.log_action(
                session_id=self.session_id,
                action_type='game_action',
                event_name='move_piece_success',
                details={
                    'piece_idx': piece_idx,
                    'from': {'x': from_x, 'y': from_y},
                    'to': {'x': to_x, 'y': to_y}
                },
                metadata=self._get_current_metadata()
            )
        
        return True, "Piece moved"
    
    def remove_piece(self, x, y):
        """Remove a piece from work area."""
        # Log attempt
        if self.session_logger:
            self.session_logger.log_action(
                session_id=self.session_id,
                action_type='game_action',
                event_name='remove_piece_attempt',
                details={'position': {'x': x, 'y': y}},
                metadata=self._get_current_metadata()
            )
        
        piece_idx = self.work_area[y][x]
        if piece_idx is None:
            if self.session_logger:
                self.session_logger.log_action(
                    session_id=self.session_id,
                    action_type='game_action',
                    event_name='remove_piece_failed',
                    details={'position': {'x': x, 'y': y}, 'error': 'no_piece_at_position'},
                    metadata=self._get_current_metadata()
                )
            return False, "No piece at position"
        
        self.work_area[y][x] = None
        
        # If this was the last placed piece, reset turn
        reset_turn = False
        if piece_idx == self.last_placed_piece:
            self.pieces_in_work_area.discard(piece_idx)
            self.last_placed_piece = None
            reset_turn = True
            # Only clear waiting flag for human helper
            if self.waiting_for_helper and self.helper_mode == 'human':
                self.waiting_for_helper = False
        
        # Log success
        if self.session_logger:
            self.session_logger.log_action(
                session_id=self.session_id,
                action_type='game_action',
                event_name='remove_piece_success',
                details={
                    'piece_idx': piece_idx,
                    'position': {'x': x, 'y': y},
                    'reset_turn': reset_turn
                },
                metadata=self._get_current_metadata()
            )
        
        return True, "Piece removed"
    
    def next_turn(self):
        """Advance to next turn (only used in human helper mode)."""
        if self.waiting_for_helper and self.helper_mode == 'human':
            return False, "Please wait for helper's response"
        
        self.last_placed_piece = None
        return True, "Next turn - you can place another piece"
    
    def add_message(self, sender, message):
        """Add a chat message."""
        print(f"[CHAT-DEBUG] add_message: session_id={self.session_id}, sender={sender}, chat_history_len={len(self.chat_history)}")
        self.chat_history.append({
            'sender': sender,
            'message': message,
            'timestamp': datetime.now().isoformat()
        })
        print(f"[CHAT-DEBUG] add_message: After append, chat_history_len={len(self.chat_history)}")
        
        # Log message
        if self.session_logger:
            self.session_logger.log_action(
                session_id=self.session_id,
                action_type='game_action',
                event_name='send_message',
                details={
                    'sender': sender,
                    'message': message,
                    'message_length': len(message),
                    'chat_history_length': len(self.chat_history)
                },
                metadata=self._get_current_metadata()
            )
        
        # If helper responded, worker can move again
        if sender == 'helper' and self.waiting_for_helper:
            self.waiting_for_helper = False
            self.last_placed_piece = None
    
    async def get_llm_helper_response(self, worker_message):
        """Get response from LLM helper."""
        if not self.agent_controller:
            return None
        
        # Build recent messages
        print(f"[CHAT-DEBUG] get_llm_helper_response: session_id={self.session_id}, total_chat_history_len={len(self.chat_history)}")
        recent_worker_messages = [
            msg['message'] for msg in self.chat_history[-10:]
            if msg['sender'] == 'worker'
        ]
        print(f"[CHAT-DEBUG] get_llm_helper_response: Extracted {len(recent_worker_messages)} worker messages")
        
        # Get PIL images for pieces
        piece_images = {}
        for idx, img_data in self.piece_images_b64.items():
            # Convert base64 back to PIL
            img_bytes = base64.b64decode(img_data['data'])
            piece_images[idx] = Image.open(io.BytesIO(img_bytes))
        
        # Get guidance
        response = await self.agent_controller.get_helper_guidance(
            self.target_area,
            self.work_area,
            piece_images,
            recent_worker_messages,
            None
        )
        
        return response
    
    async def get_llm_worker_action(self):
        """Get next action from LLM worker."""
        print(f"[DEBUG] get_llm_worker_action: ENTRY")
        if not self.agent_controller:
            print(f"[DEBUG] get_llm_worker_action: No agent_controller, returning None")
            return None
        
        print(f"[DEBUG] get_llm_worker_action: About to build recent messages")
        # Build recent messages
        recent_helper_messages = [
            msg['message'] for msg in self.chat_history[-10:]
            if msg['sender'] == 'helper'
        ]
        
        # Get PIL images for pieces
        print(f"[DEBUG] get_llm_worker_action: About to process piece images")
        piece_images = {}
        for idx, img_data in self.piece_images_b64.items():
            # Convert base64 back to PIL
            img_bytes = base64.b64decode(img_data['data'])
            piece_images[idx] = Image.open(io.BytesIO(img_bytes))
        
        # Get worker action - correct parameter order from integration.py
        print(f"[DEBUG] get_llm_worker_action: About to call agent_controller.get_worker_action()")
        action_result = await self.agent_controller.get_worker_action(
            work_area=self.work_area,
            staging_pieces=self.staging_pieces,
            piece_images=piece_images,
            recent_messages=recent_helper_messages
        )
        print(f"[DEBUG] get_llm_worker_action: agent_controller.get_worker_action() returned")
        
        return action_result


# ============================================================================
# Helper functions for managing user-specific game sessions
# ============================================================================

def get_auto_player_modes(mode: Optional[str]) -> Optional[Tuple[str, str]]:
    """Get CLI-enforced player modes, or None for manual role selection."""
    if mode is None:
        return None
    if mode == 'worker':
        return 'human', 'llm'
    if mode == 'helper':
        return 'llm', 'human'
    raise ValueError(f"Unknown auto-start mode: {mode!r}")


def get_user_session_id():
    """Get the unique session ID for the current user.
    
    Always returns game_session_id (randomly generated UUID).
    custom_session_id (from Prolific SESSION_ID) is stored separately for logging only.
    
    WARNING: This function requires Flask session context and may fail in Socket.IO handlers.
    For Socket.IO handlers, use get_session_id_from_data() instead.
    """
    try:
        # Priority 1: Use game_session_id (always randomly generated at login)
        if session.get('game_session_id'):
            return session.get('game_session_id')
        
        # Priority 2: Generate a new game_session_id if authenticated but none exists
        # This happens when upgrading from old code or in study mode before login
        if session.get('authenticated'):
            game_session_id = str(uuid.uuid4())
            session['game_session_id'] = game_session_id
            print(f"[Session] Auto-generated game session ID for authenticated user: {game_session_id}")
            return game_session_id
        
        # Priority 3: Generate for non-authenticated sessions (testing/dev mode)
        if not session.get('game_session_id'):
            game_session_id = str(uuid.uuid4())
            session['game_session_id'] = game_session_id
            print(f"[Session] Auto-generated game session ID: {game_session_id}")
            return game_session_id
        
        # Fallback: Use socket session ID
        return request.sid if hasattr(request, 'sid') else None
    except RuntimeError:
        # Flask session not available (e.g., in Socket.IO context)
        print(f"[WARNING] Flask session not available in get_user_session_id, returning request.sid")
        return request.sid if hasattr(request, 'sid') else None


def get_session_id_from_data(data):
    """Get session ID from client-provided data in Socket.IO events.
    
    This is the preferred method for Socket.IO handlers as it doesn't rely on Flask session.
    Always uses game_session_id (randomly generated UUID) for session management.
    custom_session_id (from Prolific) is stored separately for logging only.
    
    Args:
        data: The data dict from the socket event
        
    Returns:
        The session_id determined from client data: game_session_id or socket_id
    """
    flask_game_session_id = data.get('flask_game_session_id', '')
    
    # Use game_session_id if available, otherwise fall back to socket_id
    # Note: No user_id fallback to prevent reusing old sessions after cookie deletion
    if flask_game_session_id:
        print(f"[SESSION-DEBUG] get_session_id_from_data: Using flask_game_session_id={flask_game_session_id}")
        return flask_game_session_id
    else:
        print(f"[SESSION-DEBUG] get_session_id_from_data: No flask_game_session_id, using request.sid={request.sid}")
        return request.sid


def get_or_create_game_session(session_id, worker_mode='human', helper_mode='human', shared_view=True, socket_id=None):
    """Get existing game session or create new one for this user.
    
    Args:
        session_id: The primary session identifier
        worker_mode: 'human' or 'llm'
        helper_mode: 'human' or 'llm'
        shared_view: Whether helper can see worker's board
        socket_id: Optional socket ID to create an alias for the session
    """
    print(f"[DEBUG] get_or_create_game_session - session_id={session_id}, socket_id={socket_id}")
    print(f"[DEBUG] get_or_create_game_session - Current user_sessions keys: {list(user_sessions.keys())}")
    
    if session_id not in user_sessions:
        print(f"[DEBUG] Creating new GameSession for session_id: {session_id}")
        user_sessions[session_id] = GameSession(session_id, worker_mode, helper_mode, shared_view)
        print(f"[DEBUG] After creation, user_sessions keys: {list(user_sessions.keys())}")
        
        # If creating a new session and socket_id exists and points to an old session, remove the old alias
        if socket_id and socket_id in user_sessions and user_sessions[socket_id] != user_sessions[session_id]:
            print(f"[DEBUG] Removing old session alias for socket_id={socket_id}")
            del user_sessions[socket_id]
    else:
        existing = user_sessions[session_id]
        # Modes are locked in when the GameSession is first created. If a later join
        # arrives with different modes (e.g. a human opens the Helper page in a browser
        # whose session was first created in an AI-helper configuration), the stale
        # modes and agent_controller would leak in - the human helper would then see an
        # AI helper acting in their seat. Rebuild the session so the latest role
        # selection wins.
        if existing.worker_mode != worker_mode or existing.helper_mode != helper_mode:
            print(f"[DEBUG] Mode mismatch for existing session {session_id}: "
                  f"worker {existing.worker_mode}->{worker_mode}, "
                  f"helper {existing.helper_mode}->{helper_mode}. Rebuilding session.")
            # Stop any background worker loop still bound to the old session object.
            existing.trial_active = False
            existing.worker_loop_id += 1
            user_sessions[session_id] = GameSession(session_id, worker_mode, helper_mode, shared_view)
        else:
            print(f"[DEBUG] Found existing session for session_id: {session_id}")

    # If socket_id provided and different from session_id, create an alias
    if socket_id and socket_id != session_id and socket_id not in user_sessions:
        print(f"[DEBUG] Creating alias: socket_id={socket_id} -> session_id={session_id}")
        user_sessions[socket_id] = user_sessions[session_id]
        print(f"[DEBUG] After alias, user_sessions keys: {list(user_sessions.keys())}")
    elif socket_id and socket_id != session_id and socket_id in user_sessions:
        # Update the alias to point to the current session if it's different
        if user_sessions[socket_id] != user_sessions[session_id]:
            print(f"[DEBUG] Updating alias: socket_id={socket_id} -> session_id={session_id}")
            user_sessions[socket_id] = user_sessions[session_id]
        else:
            print(f"[DEBUG] Alias already correct for socket_id={socket_id}")
    
    return user_sessions[session_id]


def get_game_session():
    """Get the game session for the current request."""
    session_id = get_user_session_id()
    if not session_id:
        return None
    return user_sessions.get(session_id)
