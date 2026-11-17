"""Authoritative state and rules for one study trial."""
import copy
from typing import Any, Dict, List, Optional, Tuple

from .conditions import GRID_SIZE, TrialCondition
from .figures import figure_piece_images, figure_piece_names
from .pieces import build_piece_images, piece_names
from .views import INITIAL_CURSOR, ViewWindow, clamp_window, helper_visible_cells, worker_cell


def _empty_grid() -> List[List[Optional[int]]]:
    return [[None] * GRID_SIZE for _ in range(GRID_SIZE)]


def _in_bounds(x: int, y: int) -> bool:
    return 0 <= x < GRID_SIZE and 0 <= y < GRID_SIZE


class StudyEnvironment:
    """The Worker's board, the target, and everything the Helper's view depends on."""

    def __init__(self, trial: TrialCondition):
        self.trial = trial
        if trial.figure is not None:
            self.pieces = figure_piece_images(trial.figure)
            self.piece_names = figure_piece_names(trial.figure)
        else:
            self.pieces = build_piece_images(trial.complexity)
            self.piece_names = piece_names(trial.complexity)
        self.work_area = _empty_grid()
        self.target_area = _empty_grid()
        for tile, (x, y) in zip(trial.tiles, trial.positions):
            self.target_area[y][x] = tile
        self.turn = 0
        self.cursor: Tuple[int, int] = INITIAL_CURSOR
        self._manual_origin: Tuple[int, int] = INITIAL_CURSOR
        # The Helper's "snapshot" feedback starts as the true, empty board.
        self.snapshot_grid = copy.deepcopy(self.work_area)
        self.snapshots_sent = 0
        self.snapshot_turn: Optional[int] = None
        self.worker_notes: List[str] = []

    @property
    def solved(self) -> bool:
        return self.work_area == self.target_area

    @property
    def window(self) -> Optional[ViewWindow]:
        """The Helper's current window, or None when the view is not a partial window."""
        size = self.trial.window_cells
        if not size:
            return None
        if self.trial.fov_control == 'auto':
            return clamp_window(self.cursor[0], self.cursor[1], size)
        return clamp_window(self._manual_origin[0], self._manual_origin[1], size)

    def helper_can_see(self, x: int, y: int) -> bool:
        visible = helper_visible_cells(self.trial, self.window)
        return visible is None or (x, y) in visible

    def worker_action_allowed(self, kind: str) -> Optional[str]:
        """Return a reason the action is unavailable in this condition, or None."""
        trial = self.trial
        if kind == 'snapshot' and trial.feedback != 'snapshot':
            return "SEND SNAPSHOT is not available: the Helper already sees your board directly"
        if kind == 'point' and not (trial.window_cells and trial.fov_control == 'auto'):
            return "POINT is not available in this condition"
        if kind == 'window' and not (trial.window_cells and trial.fov_control == 'worker'):
            return "SHOW WINDOW is not available: you do not control the Helper's window"
        return None

    def apply_worker_action(self, action: Dict[str, Any]) -> Tuple[bool, str]:
        kind = action.get('action')
        blocked = self.worker_action_allowed(kind)
        if blocked:
            return False, blocked
        if kind == 'place':
            piece, (x, y) = action['piece'], action['position']
            if piece not in self.pieces:
                return False, f"Piece #{piece} does not exist"
            if not _in_bounds(x, y):
                return False, f"Position ({x}, {y}) is out of bounds"
            self.work_area[y][x] = piece
            self.cursor = (x, y)
            return True, f"Placed piece #{piece} at ({x}, {y})"
        if kind == 'move':
            (fx, fy), (tx, ty) = action['from'], action['to']
            if not (_in_bounds(fx, fy) and _in_bounds(tx, ty)):
                return False, "Move position is out of bounds"
            if self.work_area[fy][fx] is None:
                return False, f"No piece at ({fx}, {fy})"
            if self.work_area[ty][tx] is not None:
                return False, f"Position ({tx}, {ty}) is already occupied"
            self.work_area[ty][tx], self.work_area[fy][fx] = self.work_area[fy][fx], None
            self.cursor = (tx, ty)
            return True, f"Moved piece from ({fx}, {fy}) to ({tx}, {ty})"
        if kind == 'remove':
            x, y = action['position']
            if not _in_bounds(x, y):
                return False, f"Position ({x}, {y}) is out of bounds"
            if self.work_area[y][x] is None:
                return False, f"No piece at ({x}, {y}) to remove"
            self.work_area[y][x] = None
            self.cursor = (x, y)
            return True, f"Removed piece from ({x}, {y})"
        if kind == 'point':
            x, y = action['position']
            if not _in_bounds(x, y):
                return False, f"Position ({x}, {y}) is out of bounds"
            self.cursor = (x, y)
            return True, f"Pointed at ({x}, {y})"
        if kind == 'window':
            x, y = action['position']
            if not _in_bounds(x, y):
                return False, f"Position ({x}, {y}) is out of bounds"
            self._manual_origin = (x, y)
            return True, f"Moved the Helper's window to ({x}, {y})"
        if kind == 'snapshot':
            self.snapshot_grid = copy.deepcopy(self.work_area)
            self.snapshots_sent += 1
            self.snapshot_turn = self.turn
            return True, f"Sent snapshot #{self.snapshots_sent}"
        return False, f"Unknown action {kind!r}"

    def apply_helper_action(self, action: Dict[str, Any]) -> Tuple[bool, str]:
        if action.get('action') != 'look':
            return False, f"Unknown action {action.get('action')!r}"
        if not (self.trial.window_cells and self.trial.fov_control == 'helper'):
            return False, "LOOK is not available: you do not control the window"
        x, y = action['position']
        if not _in_bounds(x, y):
            return False, f"Position ({x}, {y}) is out of bounds"
        transform = self.trial.transform
        if transform.is_identity:
            self._manual_origin = (x, y)
        else:
            # LOOK names the top-left cell in the Helper's own (rotated) view: move the window
            # to the Worker cells shown there.
            size = self.trial.window_cells
            shown = clamp_window(x, y, size)
            cells = [worker_cell((shown.x + dx, shown.y + dy), transform) for dx in range(size) for dy in range(size)]
            self._manual_origin = (min(c[0] for c in cells), min(c[1] for c in cells))
        return True, f"Moved your window to ({x}, {y})"
