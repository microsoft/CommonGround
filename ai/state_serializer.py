"""
Backward-compatibility shim - re-exports from grid_renderer and action_parser.
"""
from .grid_renderer import GridStateSerializer, describe_piece_simple
from .action_parser import ActionParser

__all__ = ['GridStateSerializer', 'ActionParser', 'describe_piece_simple']