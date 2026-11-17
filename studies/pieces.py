"""The two eight-piece sets that manipulate linguistic complexity.

Solid pieces are easy to name (high codability and discriminability). Patterned
pieces reuse the app's existing tile patterns, which have no shared names and so
must be grounded in conversation, standing in for the paper's tartan plaids.
"""
from typing import Dict, Tuple

from PIL import Image

from puzzle_constants import generate_pattern_block

PIECE_IMAGE_SIZE = 110  # matches the 120px board cell less padding, so no resampling

SOLID_COLORS: Tuple[Tuple[str, str], ...] = (
    ('red', '#D32F2F'),
    ('orange', '#F57C00'),
    ('yellow', '#FBC02D'),
    ('green', '#388E3C'),
    ('blue', '#1976D2'),
    ('purple', '#7B1FA2'),
    ('pink', '#F48FB1'),
    ('black', '#212121'),
)

# Indices into puzzle_constants.TILE_PATTERNS.
PATTERNED_TILES: Tuple[int, ...] = (0, 3, 4, 6, 7, 10, 15, 22)


def build_piece_images(complexity: str, size: int = PIECE_IMAGE_SIZE) -> Dict[int, Image.Image]:
    """Return piece images keyed by the local piece number 0-7."""
    if complexity == 'solid':
        return {i: Image.new('RGB', (size, size), color) for i, (_, color) in enumerate(SOLID_COLORS)}
    if complexity == 'patterned':
        return {i: generate_pattern_block(size=size, piece_idx=tile)[0] for i, tile in enumerate(PATTERNED_TILES)}
    raise ValueError(f"Unknown piece complexity {complexity!r}")


def piece_names(complexity: str) -> Dict[int, str]:
    """Human-readable names for logs and the observer only; never shown to agents."""
    if complexity == 'solid':
        return {i: name for i, (name, _) in enumerate(SOLID_COLORS)}
    if complexity == 'patterned':
        from puzzle_constants import TILE_PATTERNS
        return {i: TILE_PATTERNS[tile][1] for i, tile in enumerate(PATTERNED_TILES)}
    raise ValueError(f"Unknown piece complexity {complexity!r}")
