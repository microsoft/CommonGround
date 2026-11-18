"""Rendering of what each agent sees.

This module is the only place that decides what the Worker and Helper observe.
Hidden cells are drawn black ("unobserved"), never as empty cells.
"""
import base64
import io
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageOps

from ai.grid_renderer import GridStateSerializer

from .conditions import GRID_SIZE, TrialCondition, ViewTransform

CELL_SIZE = 120
TRANSFORM_FILL = (190, 190, 190)  # visible, so the rotated workspace keeps a boundary
HIDDEN_FILL = (0, 0, 0)
BOARD_OUTLINE = (40, 40, 40)
WINDOW_OUTLINE = (220, 30, 30)
INITIAL_CURSOR = (GRID_SIZE // 2, GRID_SIZE // 2)
AXIS_MARGIN = 30
COLUMN_LETTERS = 'ABCDEF'

_serializer = GridStateSerializer(GRID_SIZE)


@dataclass(frozen=True)
class ViewWindow:
    """A square block of cells with its top-left cell at (x, y)."""
    x: int
    y: int
    size: int

    def cells(self) -> FrozenSet[Tuple[int, int]]:
        return frozenset((self.x + dx, self.y + dy) for dx in range(self.size) for dy in range(self.size))


def clamp_window(x: int, y: int, size: int) -> ViewWindow:
    """Keep a window inside the grid; the requested cell stays inside it."""
    limit = GRID_SIZE - size
    return ViewWindow(min(max(x, 0), limit), min(max(y, 0), limit), size)


def encode_png(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return base64.b64encode(buffer.getvalue()).decode('ascii')


def decode_png(data: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(data))).convert('RGB')


def render_board(grid, piece_images: Dict[int, Image.Image], cell_size: int = CELL_SIZE,
                 border_width: int = 1, seamless: bool = False) -> Image.Image:
    """Render a grid exactly as the existing agents see it.

    ``seamless`` draws each piece edge to edge with no frame, so pieces cut from
    one picture join up into the continuous drawing. Grid lines are drawn on top
    when ``border_width`` is set.
    """
    if not seamless:
        return decode_png(_serializer.serialize_grid_png(
            grid, piece_images, cell_size=cell_size, border_width=border_width))
    size = GRID_SIZE * cell_size
    image = Image.new('RGB', (size, size), 'white')
    for y in range(GRID_SIZE):
        for x in range(GRID_SIZE):
            piece = grid[y][x]
            if piece is not None and piece in piece_images:
                tile = piece_images[piece]
                if tile.size != (cell_size, cell_size):
                    tile = tile.resize((cell_size, cell_size), Image.Resampling.LANCZOS)
                image.paste(tile, (x * cell_size, y * cell_size))
    if border_width:
        draw = ImageDraw.Draw(image)
        for i in range(GRID_SIZE + 1):
            edge = min(i * cell_size, size - 1)
            draw.line([(edge, 0), (edge, size - 1)], fill='gray', width=border_width)
            draw.line([(0, edge), (size - 1, edge)], fill='gray', width=border_width)
    return image


def blackout(image: Image.Image, visible: Optional[FrozenSet[Tuple[int, int]]],
             cell_size: int = CELL_SIZE) -> Image.Image:
    """Black out every cell not in ``visible``; None means everything is visible."""
    if visible is None:
        return image
    image = image.copy()
    draw = ImageDraw.Draw(image)
    for y in range(GRID_SIZE):
        for x in range(GRID_SIZE):
            if (x, y) not in visible:
                draw.rectangle([x * cell_size, y * cell_size,
                                (x + 1) * cell_size - 1, (y + 1) * cell_size - 1], fill=HIDDEN_FILL)
    return image


def outline_window(image: Image.Image, window: ViewWindow, cell_size: int = CELL_SIZE) -> Image.Image:
    image = image.copy()
    ImageDraw.Draw(image).rectangle(
        [window.x * cell_size, window.y * cell_size,
         (window.x + window.size) * cell_size - 1, (window.y + window.size) * cell_size - 1],
        outline=WINDOW_OUTLINE, width=5)
    return image


def _font() -> ImageFont.ImageFont:
    for name in ('arial.ttf', 'Arial.ttf', 'DejaVuSans.ttf'):
        try:
            return ImageFont.truetype(name, 18)
        except OSError:
            continue
    return ImageFont.load_default()


def add_axis_labels(image: Image.Image, columns=COLUMN_LETTERS, rows=None,
                    cell_size: int = CELL_SIZE) -> Image.Image:
    """Label each column and row in a margin above and to the left of the board.

    Defaults to columns A-F and rows 1-6, used by the Helper to aim its own window.
    """
    rows = rows or [str(i + 1) for i in range(GRID_SIZE)]
    canvas = Image.new('RGB', (image.width + AXIS_MARGIN, image.height + AXIS_MARGIN), 'white')
    canvas.paste(image, (AXIS_MARGIN, AXIS_MARGIN))
    draw = ImageDraw.Draw(canvas)
    font = _font()
    for i in range(GRID_SIZE):
        centre = AXIS_MARGIN + i * cell_size + cell_size // 2
        draw.text((centre, AXIS_MARGIN // 2), columns[i], fill='black', anchor='mm', font=font)
        draw.text((AXIS_MARGIN // 2, centre), rows[i], fill='black', anchor='mm', font=font)
    return canvas


WORKER_AXIS = [str(i) for i in range(GRID_SIZE)]


def add_board_outline(image: Image.Image) -> Image.Image:
    """Frame the whole board without drawing internal grid lines.

    The Helper's target has no grid, but without an outline it is pieces on blank
    white and the board's edges cannot be seen. Humans see the target on a framed
    canvas, so the frame is drawn before any rotation and turns with the view.
    """
    image = image.copy()
    ImageDraw.Draw(image).rectangle([0, 0, image.width - 1, image.height - 1], outline=BOARD_OUTLINE, width=4)
    return image


def apply_transform(image: Image.Image, transform: ViewTransform) -> Image.Image:
    """Flip, then rotate clockwise; the canvas grows so nothing is cropped."""
    if transform.flip == 'horizontal':
        image = ImageOps.mirror(image)
    elif transform.flip == 'vertical':
        image = ImageOps.flip(image)
    if transform.degrees % 360:
        resample = Image.Resampling.NEAREST if transform.degrees % 90 == 0 else Image.Resampling.BICUBIC
        image = image.rotate(-transform.degrees, resample=resample, expand=True, fillcolor=TRANSFORM_FILL)
    return image


def map_point(point: Tuple[float, float], size: float, transform: ViewTransform) -> Tuple[float, float]:
    """Where a point of a square ``size`` image lands after ``apply_transform``."""
    import math
    x, y = point[0] - size / 2, point[1] - size / 2
    if transform.flip == 'horizontal':
        x = -x
    elif transform.flip == 'vertical':
        y = -y
    theta = math.radians(transform.degrees)
    cos, sin = math.cos(theta), math.sin(theta)
    new_size = size * (abs(cos) + abs(sin))
    return new_size / 2 + x * cos - y * sin, new_size / 2 + x * sin + y * cos


def parse_column_row(text: str) -> Optional[Tuple[int, int]]:
    """Parse a Helper window target such as 'C3' into a (column, row) cell."""
    text = text.strip().upper()
    if len(text) == 2 and text[0] in COLUMN_LETTERS and text[1] in '123456':
        return COLUMN_LETTERS.index(text[0]), int(text[1]) - 1
    return None


def helper_cell(cell: Tuple[int, int], transform: ViewTransform) -> Tuple[int, int]:
    """Where the Worker's cell (x, y) appears in the Helper's view (transforms by multiples of 90 degrees)."""
    size = GRID_SIZE * CELL_SIZE
    px, py = map_point(((cell[0] + 0.5) * CELL_SIZE, (cell[1] + 0.5) * CELL_SIZE), size, transform)
    return int(px // CELL_SIZE), int(py // CELL_SIZE)


def worker_cell(cell: Tuple[int, int], transform: ViewTransform) -> Tuple[int, int]:
    """The Worker's cell shown at (x, y) in the Helper's view; the inverse of ``helper_cell``."""
    return next((x, y) for x in range(GRID_SIZE) for y in range(GRID_SIZE)
                if helper_cell((x, y), transform) == tuple(cell))


@dataclass
class ObservationImage:
    label: str
    png_b64: str


@dataclass
class Observation:
    """Exactly what one agent receives in a turn (besides the dialogue)."""
    role: str
    images: List[ObservationImage] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_content(self, instruction: str) -> list:
        content = []
        for image in self.images:
            content.append({"type": "text", "text": f"External information: {image.label}"})
            content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image.png_b64}"}})
        text = "\n".join(self.notes + [instruction]) if self.notes else instruction
        content.append({"type": "text", "text": text})
        return content


def helper_visible_cells(trial: TrialCondition, window: Optional[ViewWindow]) -> Optional[FrozenSet[Tuple[int, int]]]:
    if trial.fov_size == 'full':
        return None
    if trial.fov_size == 'none':
        return frozenset()
    return window.cells() if window else frozenset()


def _seamless(env) -> bool:
    """Figure pieces are cut from one picture, so they are drawn edge to edge."""
    return env.trial.figure is not None


def build_helper_observation(env) -> Observation:
    trial = env.trial
    seamless = _seamless(env)
    target = add_board_outline(render_board(env.target_area, env.pieces, border_width=0, seamless=seamless))
    target = apply_transform(target, trial.transform)
    source = env.work_area if trial.feedback == 'immediate' else env.snapshot_grid
    # Deliberately without the Worker's 0-5 numbering: numbers that turn with the
    # view would hand the Helper the mapping the rotation condition takes away.
    board = blackout(render_board(source, env.pieces, seamless=seamless),
                     helper_visible_cells(trial, env.window))
    rotated = not trial.transform.is_identity
    if trial.fov_control == 'helper' and not rotated:
        board = add_axis_labels(board)
    board = apply_transform(board, trial.transform)
    if trial.fov_control == 'helper' and rotated:
        # Labelled after turning, in the Helper's own frame: labels that turned with the board
        # would show the Helper the mapping the rotation takes away. LOOK uses these labels.
        board = add_axis_labels(board)

    notes = []
    if trial.feedback == 'snapshot':
        if env.snapshots_sent:
            notes.append(f"The board image is snapshot #{env.snapshots_sent}, sent by the Worker "
                         f"after Worker turn {env.snapshot_turn}.")
        else:
            notes.append("The Worker has not sent a snapshot yet; the board image shows the empty starting board.")
    if trial.fov_control == 'helper' and env.window is not None:
        notes.append(f"Your window currently shows {window_label(env.window, trial.transform)}. Use LOOK to move it.")
    return Observation('helper', [
        ObservationImage("This is the target pattern the Worker must build:", encode_png(target)),
        ObservationImage("This is what you can currently see of the Worker's board (only the board, never the "
                         "Worker's unplaced pieces):", encode_png(board)),
    ], notes)


def window_label(window: ViewWindow, transform: Optional[ViewTransform] = None) -> str:
    """The window's cells in the Helper's column-letter, row-number labels, e.g. 'C3 to D4'.

    With a rotated view the labels are the Helper's own, so the window is named as the Helper sees it.
    """
    x, y = window.x, window.y
    if transform is not None and not transform.is_identity:
        cells = [helper_cell(cell, transform) for cell in window.cells()]
        x, y = min(c[0] for c in cells), min(c[1] for c in cells)
    first = f"{COLUMN_LETTERS[x]}{y + 1}"
    if window.size == 1:
        return f"cell {first}"
    last = f"{COLUMN_LETTERS[x + window.size - 1]}{y + window.size}"
    return f"cells {first} to {last}"


def build_worker_observation(env) -> Observation:
    trial = env.trial
    board = render_board(env.work_area, env.pieces, seamless=_seamless(env))
    if env.window is not None:
        board = outline_window(board, env.window)
    # Numbered 0-5 so the Worker can read action coordinates instead of counting cells.
    board = add_axis_labels(board, WORKER_AXIS, WORKER_AXIS)
    pieces_png = _serializer.serialize_piece_images_png(env.pieces, pieces_per_row=4)
    label = ("This is the current state of your board. Columns are numbered 0-5 along the top and rows "
             "0-5 down the side; a cell's position is (column, row).")
    if env.window is not None:
        label += " The red frame marks the part the Helper can see."
    notes = list(env.worker_notes)
    return Observation('worker', [
        ObservationImage(label, encode_png(board)),
        ObservationImage("These are the pieces you can use:", pieces_png),
    ], notes)


def build_truth_images(env, cell_size: int = 60) -> Dict[str, str]:
    """Observer-only ground truth; never passed to an agent."""
    seamless = _seamless(env)
    return {
        'target': encode_png(render_board(env.target_area, env.pieces, cell_size, border_width=0, seamless=seamless)),
        'board': encode_png(render_board(env.work_area, env.pieces, cell_size, seamless=seamless)),
    }
