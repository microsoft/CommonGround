"""Circle-and-stem figures: a piece set cut from one picture.

The picture is a circle drawn across a 3x3 block of cells with a straight stem
sticking out from its edge, like a lollipop, and each piece is one cell of the
drawing. The circle's eight rim cells hold arcs, the centre cell is blank (no
piece goes there), and the stem crosses two or three cells outside the block, so
the target is an irregular shape. A partial view suggests the rest of the circle,
since a visible arc implies the whole ring, but not where the stem is. Many
pieces are turned or mirrored copies of one another, so a piece cannot be named
by its shape once the two views are rotated.

The staging area holds the target cells plus distractors: turned or mirrored
copies of target cells that look different from every target cell. The order is
shuffled, so a piece's number says nothing about where it belongs. Pieces are
never turned by the agents; each is placed as shown.
"""
import math
import random
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, FrozenSet, List, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageStat

BLOCK = 3                 # the circle covers BLOCK x BLOCK cells
DISTRACTORS = 7           # staging pieces that are not in the target
PIECE_PX = 120            # a full board cell (views.CELL_SIZE), so pieces join edge to edge

RADIUS = 1.3              # circle radius, in cells; the ring passes through all eight rim cells
# Stem lengths beyond the circle, in cells. Each ends part-way into its last cell; between them
# they give sixteen usable directions (1.9 for 15, 75, 105, ... degrees; 1.5 for 30, 60, 120, ...).
STEM_LENGTHS = (1.5, 1.9)
STROKE = 0.065            # stroke width, in cells
STEM_ANGLES = tuple(range(0, 360, 15))   # degrees, clockwise from pointing right
CENTRE = (BLOCK / 2, BLOCK / 2)
CIRCLE_CELLS: FrozenSet[Tuple[int, int]] = frozenset(
    (x, y) for y in range(BLOCK) for x in range(BLOCK) if (x, y) != (1, 1))
# The drawing is rendered on a canvas of cells CANVAS_MIN .. CANVAS_MIN + CANVAS_CELLS - 1,
# in the same coordinates as the circle's block (whose top-left cell is (0, 0)).
CANVAS_MIN = -2
CANVAS_CELLS = 7
BACKGROUND = (255, 255, 255)
INK = (25, 25, 25)
SUPERSAMPLE = 4
# Mean absolute grey-level difference below which two pieces count as looking the same.
# Identical-looking pieces differ by about 1-2 from anti-aliasing; clearly different ones by 10 or more.
SAME_LOOK = 10.0
# A stem crossing a cell (outside the circle) for less than this, in cells, leaves an easy-to-miss sliver.
MIN_STEM_IN_CELL = 0.35
# Grey levels: a cell whose darkest pixel is below INKED is part of the picture; one whose darkest
# pixel lies between INKED and BLANK holds a faint fleck of stroke (the stem grazing a corner).
INKED, BLANK = 100, 235

OPS = ('as drawn', 'turned 90', 'turned 180', 'turned 270', 'mirrored left-right',
       'mirrored top-bottom', 'mirrored on the main diagonal', 'mirrored on the other diagonal')
_TRANSPOSE = {
    'turned 90': Image.Transpose.ROTATE_270,   # PIL rotates anticlockwise; these names are clockwise
    'turned 180': Image.Transpose.ROTATE_180,
    'turned 270': Image.Transpose.ROTATE_90,
    'mirrored left-right': Image.Transpose.FLIP_LEFT_RIGHT,
    'mirrored top-bottom': Image.Transpose.FLIP_TOP_BOTTOM,
    'mirrored on the main diagonal': Image.Transpose.TRANSPOSE,
    'mirrored on the other diagonal': Image.Transpose.TRANSVERSE,
}
RIM_NAMES = {(0, 0): 'top-left', (1, 0): 'top', (2, 0): 'top-right', (0, 1): 'left',
             (2, 1): 'right', (0, 2): 'bottom-left', (1, 2): 'bottom', (2, 2): 'bottom-right'}


@dataclass(frozen=True)
class FigureSpec:
    """Everything needed to redraw a trial's pieces.

    ``cells`` are the picture's cells, in the circle block's coordinates (stem cells
    can be negative or beyond 2). ``pieces[i]`` is staging piece ``i``: cell (x, y)
    shown as one of ``OPS``. The target uses the pieces whose op is 'as drawn'.
    """
    stem_angle: int
    stem_length: float
    cells: Tuple[Tuple[int, int], ...]
    pieces: Tuple[Tuple[int, int, str], ...]

    def target_piece(self, x: int, y: int) -> int:
        return self.pieces.index((x, y, OPS[0]))

    @property
    def size(self) -> Tuple[int, int]:
        """Width and height, in cells, of the box around the picture."""
        xs, ys = [x for x, _ in self.cells], [y for _, y in self.cells]
        return max(xs) - min(xs) + 1, max(ys) - min(ys) + 1


def _stem(stem_angle: int, stem_length: float):
    """The stem's start (on the circle) and its unit direction, in cell units."""
    angle = math.radians(stem_angle)
    dx, dy = math.cos(angle), math.sin(angle)
    return (CENTRE[0] + RADIUS * dx, CENTRE[1] + RADIUS * dy), (dx, dy)


def stem_length_in_cell(stem_angle: int, stem_length: float, x: int, y: int) -> float:
    """Length of the stem inside cell (x, y), in cells (Liang-Barsky clipping)."""
    (px, py), (dx, dy) = _stem(stem_angle, stem_length)
    low, high = 0.0, stem_length
    for p, d, lo, hi in ((px, dx, x, x + 1), (py, dy, y, y + 1)):
        if abs(d) < 1e-12:
            if not lo <= p <= hi:
                return 0.0
            continue
        t1, t2 = (lo - p) / d, (hi - p) / d
        low, high = max(low, min(t1, t2)), min(high, max(t1, t2))
    return max(0.0, high - low)


def has_stem_slivers(stem_angle: int, stem_length: float) -> bool:
    """Whether the stem only nicks a cell outside the circle (the rim cells hold arcs anyway)."""
    for y in range(CANVAS_MIN, CANVAS_MIN + CANVAS_CELLS):
        for x in range(CANVAS_MIN, CANVAS_MIN + CANVAS_CELLS):
            if (x, y) not in CIRCLE_CELLS and 0 < stem_length_in_cell(stem_angle, stem_length, x, y) < MIN_STEM_IN_CELL:
                return True
    return False


@lru_cache(maxsize=64)
def render_figure(stem_angle: int, stem_length: float, piece_px: int = PIECE_PX) -> Image.Image:
    """The whole canvas; cell (x, y) is at pixel ((x - CANVAS_MIN) * piece_px, ...)."""
    size = CANVAS_CELLS * piece_px * SUPERSAMPLE
    cell = size / CANVAS_CELLS
    image = Image.new('RGB', (size, size), BACKGROUND)
    draw = ImageDraw.Draw(image)
    width = max(1, round(STROKE * cell))

    def px(point):
        return (point[0] - CANVAS_MIN) * cell, (point[1] - CANVAS_MIN) * cell

    cx, cy = px(CENTRE)
    radius = RADIUS * cell
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], outline=INK, width=width)
    (sx, sy), (dx, dy) = _stem(stem_angle, stem_length)
    # Start the stem half a stroke inside the ring so the two join without a gap.
    start = px((sx - dx * STROKE / 2, sy - dy * STROKE / 2))
    end = px((sx + dx * stem_length, sy + dy * stem_length))
    draw.line([start, end], fill=INK, width=width)
    return image.resize((CANVAS_CELLS * piece_px,) * 2, Image.Resampling.LANCZOS)


def cell_image(stem_angle: int, stem_length: float, x: int, y: int, op: str = OPS[0],
               piece_px: int = PIECE_PX) -> Image.Image:
    picture = render_figure(stem_angle, stem_length, piece_px)
    left, top = (x - CANVAS_MIN) * piece_px, (y - CANVAS_MIN) * piece_px
    image = picture.crop((left, top, left + piece_px, top + piece_px))
    return image if op == OPS[0] else image.transpose(_TRANSPOSE[op])


def darkest(image: Image.Image) -> int:
    return ImageStat.Stat(image.convert('L')).extrema[0][0]


def look_difference(a: Image.Image, b: Image.Image) -> float:
    return ImageStat.Stat(ImageChops.difference(a.convert('L'), b.convert('L'))).mean[0]


def picture_cells(stem_angle: int, stem_length: float):
    """The inked cells, or None if the stem leaves a faint fleck in a cell (grazing a corner)."""
    cells: List[Tuple[int, int]] = []
    for y in range(CANVAS_MIN, CANVAS_MIN + CANVAS_CELLS):
        for x in range(CANVAS_MIN, CANVAS_MIN + CANVAS_CELLS):
            level = darkest(cell_image(stem_angle, stem_length, x, y))
            if level < INKED:
                cells.append((x, y))
            elif level < BLANK:
                return None
    return cells


def stem_is_invariant(stem_angle: int, transform) -> bool:
    """Whether the transform's flip and rotation leave the picture's shape unchanged.

    The circle always maps onto itself, so the shape is unchanged exactly when the
    stem's direction is. Then a rotated view would show the Helper the aligned
    picture. ``transform`` needs ``flip`` and ``degrees``, as in ``ViewTransform``.
    """
    angle = math.radians(stem_angle)
    x, y = math.cos(angle), math.sin(angle)
    if transform.flip == 'horizontal':
        x = -x
    elif transform.flip == 'vertical':
        y = -y
    theta = math.radians(transform.degrees)
    cos, sin = math.cos(theta), math.sin(theta)
    x, y = x * cos - y * sin, x * sin + y * cos
    return abs(x - math.cos(angle)) < 1e-9 and abs(y - math.sin(angle)) < 1e-9


def generate_figure(rng: random.Random, avoid_transform=None) -> FigureSpec:
    """Choose the stem's direction and length and the shuffled staging pieces.

    ``avoid_transform`` rejects directions the transform leaves unchanged.
    """
    options = [(angle, length) for angle in STEM_ANGLES for length in STEM_LENGTHS]
    rng.shuffle(options)
    for stem_angle, stem_length in options:
        if avoid_transform is not None and stem_is_invariant(stem_angle, avoid_transform):
            continue
        if has_stem_slivers(stem_angle, stem_length):
            continue
        cells = picture_cells(stem_angle, stem_length)
        if cells is None:
            continue
        chosen = [cell_image(stem_angle, stem_length, x, y) for x, y in cells]
        if any(look_difference(a, b) < SAME_LOOK for i, a in enumerate(chosen) for b in chosen[i + 1:]):
            continue  # two target cells would be interchangeable
        candidates = [(x, y, op) for x, y in cells for op in OPS[1:]]
        rng.shuffle(candidates)
        distractors = []
        for x, y, op in candidates:
            image = cell_image(stem_angle, stem_length, x, y, op)
            if all(look_difference(image, other) >= SAME_LOOK for other in chosen):
                distractors.append((x, y, op))
                chosen.append(image)
                if len(distractors) == DISTRACTORS:
                    break
        else:
            continue
        pieces = [(x, y, OPS[0]) for x, y in cells] + distractors
        rng.shuffle(pieces)
        return FigureSpec(stem_angle, stem_length, tuple(cells), tuple(pieces))
    raise RuntimeError("Could not generate a circle-and-stem figure with distinct pieces")


def figure_target(spec: FigureSpec, origin: Tuple[int, int]):
    """Target tiles and board positions, with the top-left of the picture's box at ``origin``."""
    min_x = min(x for x, _ in spec.cells)
    min_y = min(y for _, y in spec.cells)
    tiles = tuple(spec.target_piece(x, y) for x, y in spec.cells)
    positions = tuple((origin[0] + x - min_x, origin[1] + y - min_y) for x, y in spec.cells)
    return tiles, positions


def figure_piece_images(spec: FigureSpec, piece_px: int = PIECE_PX) -> Dict[int, Image.Image]:
    return {i: cell_image(spec.stem_angle, spec.stem_length, x, y, op, piece_px)
            for i, (x, y, op) in enumerate(spec.pieces)}


def _cell_name(spec: FigureSpec, x: int, y: int) -> str:
    if (x, y) in RIM_NAMES:
        name = f"{RIM_NAMES[(x, y)]} rim cell"
        on_stem = stem_length_in_cell(spec.stem_angle, spec.stem_length, x, y) > 0
        return name + (", with the stem's base" if on_stem else '')
    (sx, sy), (dx, dy) = _stem(spec.stem_angle, spec.stem_length)
    along = ((x + 0.5 - sx) * dx + (y + 0.5 - sy) * dy)
    return f"stem cell about {max(1, round(along + 0.5))} out"


def figure_piece_names(spec: FigureSpec) -> Dict[int, str]:
    """Names for logs and the observer only; never shown to agents."""
    names = {}
    for i, (x, y, op) in enumerate(spec.pieces):
        name = _cell_name(spec, x, y)
        names[i] = name if op == OPS[0] else f"{name}, {op} (distractor)"
    return names
