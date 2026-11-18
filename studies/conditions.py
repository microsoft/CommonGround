"""Experimental designs and seeded trial schedules.

Experiment 2 (rotation): the Helper's view of both the target and the Worker's
workspace is aligned with, or flipped and rotated relative to, the Worker's view,
crossed with immediate feedback versus Worker-sent snapshots. The piece set
(solid, patterned or circle-and-stem figure) is a between-pair factor.

Experiment 3 (field of view): how much of the Worker's workspace the Helper can
see (none, small, large, full) crossed with the piece set within a pair (by
default solid and patterned, as in the paper). Who controls the window
(automatic, Worker, Helper) is a between-pair factor.
"""
import random
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple

from .figures import FigureSpec, figure_target, generate_figure

GRID_SIZE = 6
PIECES_PER_SET = 8
TARGET_PIECES = 4

EXPERIMENTS = ('rotation', 'field_of_view')
# 'figure' is a circle with a stem sticking out of it, cut into cells (see figures.py).
COMPLEXITIES = ('solid', 'patterned', 'figure')
COMPLEXITY_LABELS = {'solid': 'solid colours', 'patterned': 'patterned', 'figure': 'circle-and-stem'}
DEFAULT_FOV_COMPLEXITIES = ('solid', 'patterned')
FEEDBACK_MODES = ('immediate', 'snapshot')
ALIGNMENTS = ('aligned', 'rotated')
FLIPS = ('horizontal', 'vertical')
ROTATION_DEGREES = (45, 90, 135)
FOV_SIZES = ('full', 'large', 'small', 'none')
# Window edge length in cells: small = one piece, large = four pieces (2x2).
FOV_WINDOW_CELLS = {'small': 1, 'large': 2}
FOV_CONTROLS = ('auto', 'worker', 'helper')
# Field-of-view study: the Helper's views aligned with the Worker's, or all rotated (between pairs).
FOV_ALIGNMENTS = ('aligned', 'rotated')

DEFAULT_TRIALS_PER_BLOCK = {'rotation': 6, 'field_of_view': 4}
# How often a Helper that controls its window may LOOK per turn. Each look also adds to a
# trial's cost (turns_plus_looks), since moving the window costs a human Helper time.
LOOKS_PER_TURN = 1


@dataclass(frozen=True)
class ViewTransform:
    """Geometric transform applied to the Helper's views (flip, then clockwise rotation)."""
    flip: str = 'none'
    degrees: int = 0

    @property
    def is_identity(self) -> bool:
        return self.flip == 'none' and self.degrees == 0


# Rotated field-of-view trials use the rotation study's seed-0 transform (a reflection across the
# anti-diagonal). Multiples of 90 degrees keep the window's cells whole cells in the Helper's view.
FOV_ROTATION = ViewTransform('horizontal', 90)


@dataclass(frozen=True)
class TrialCondition:
    experiment: str
    trial_id: str
    block: int
    trial: int
    complexity: str
    feedback: str
    alignment: str
    transform: ViewTransform
    fov_size: str
    fov_control: str
    tiles: Tuple[int, ...]
    positions: Tuple[Tuple[int, int], ...]
    figure: Optional[FigureSpec] = None

    @property
    def window_cells(self) -> int:
        """Edge length of the Helper's window, or 0 when it is not a partial window."""
        return FOV_WINDOW_CELLS.get(self.fov_size, 0)

    @property
    def piece_count(self) -> int:
        """Pieces in the Worker's staging area."""
        return len(self.figure.pieces) if self.figure else PIECES_PER_SET

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StudyConfig:
    """Everything that determines a schedule, so a seed reproduces a run."""
    experiment: str
    seed: int = 0
    complexity: Optional[str] = None
    fov_control: Optional[str] = None
    trials_per_block: Optional[int] = None
    disclose_view_differences: bool = True
    # Field-of-view study: the piece sets crossed with the window sizes within a pair.
    complexities: Tuple[str, ...] = DEFAULT_FOV_COMPLEXITIES
    fov_alignment: str = 'aligned'

    def validate(self) -> None:
        if self.experiment not in EXPERIMENTS:
            raise ValueError(f"Unknown experiment {self.experiment!r}; expected one of {EXPERIMENTS}")
        if self.fov_alignment not in FOV_ALIGNMENTS:
            raise ValueError(f"fov_alignment must be one of {FOV_ALIGNMENTS}, got {self.fov_alignment!r}")
        if self.experiment == 'rotation' and self.fov_alignment != 'aligned':
            raise ValueError("fov_alignment only applies to the field-of-view study")
        if self.experiment == 'rotation' and self.complexity not in COMPLEXITIES:
            raise ValueError(f"Rotation study needs complexity in {COMPLEXITIES}, got {self.complexity!r}")
        if self.experiment == 'field_of_view':
            if self.fov_control not in FOV_CONTROLS:
                raise ValueError(f"Field-of-view study needs fov_control in {FOV_CONTROLS}, got {self.fov_control!r}")
            if not self.complexities:
                raise ValueError("Field-of-view study needs at least one piece set")
            unknown = [c for c in self.complexities if c not in COMPLEXITIES]
            if unknown:
                raise ValueError(f"Unknown piece set(s) {unknown}; expected some of {COMPLEXITIES}")
            if len(set(self.complexities)) != len(self.complexities):
                raise ValueError(f"Piece sets must not repeat: {list(self.complexities)}")
        if self.trials_per_block is not None and self.trials_per_block < 1:
            raise ValueError("trials_per_block must be at least 1")

    @property
    def resolved_trials_per_block(self) -> int:
        return self.trials_per_block or DEFAULT_TRIALS_PER_BLOCK[self.experiment]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _random_shape(rng: random.Random) -> List[Tuple[int, int]]:
    """A connected four-cell shape that is not a 2x2 square.

    A square would always fit inside the large (2x2) window and remove the
    difference between the large and full views.
    """
    while True:
        cells = {(0, 0)}
        while len(cells) < TARGET_PIECES:
            x, y = rng.choice(sorted(cells))
            dx, dy = rng.choice(((1, 0), (-1, 0), (0, 1), (0, -1)))
            cells.add((x + dx, y + dy))
        min_x = min(x for x, _ in cells)
        min_y = min(y for _, y in cells)
        shape = sorted((x - min_x, y - min_y) for x, y in cells)
        width = max(x for x, _ in shape) + 1
        height = max(y for _, y in shape) + 1
        if max(width, height) >= 3:
            return shape


def generate_target(rng: random.Random) -> Tuple[Tuple[int, ...], Tuple[Tuple[int, int], ...]]:
    """Choose four of the eight pieces and a connected layout somewhere on the grid."""
    shape = _random_shape(rng)
    width = max(x for x, _ in shape) + 1
    height = max(y for _, y in shape) + 1
    offset_x = rng.randint(0, GRID_SIZE - width)
    offset_y = rng.randint(0, GRID_SIZE - height)
    positions = [(x + offset_x, y + offset_y) for x, y in shape]
    rng.shuffle(positions)
    tiles = rng.sample(range(PIECES_PER_SET), TARGET_PIECES)
    return tuple(tiles), tuple(positions)


def _trial(config: StudyConfig, block: int, trial: int, **factors: Any) -> TrialCondition:
    rng = random.Random(f"target:{config.experiment}:{config.seed}:{block}:{trial}")
    figure = None
    if factors['complexity'] == 'figure':
        # Every trial of a rotation pair avoids lines its rotated view would leave unchanged,
        # so aligned and rotated blocks draw figures from the same set.
        figure = generate_figure(rng, avoid_transform=factors.get('pair_transform'))
        width, height = figure.size
        origin = (rng.randint(0, GRID_SIZE - width), rng.randint(0, GRID_SIZE - height))
        tiles, positions = figure_target(figure, origin)
    else:
        tiles, positions = generate_target(rng)
    fov_size = factors.get('fov_size', 'full')
    fov_control = factors.get('fov_control', 'n/a')
    if fov_size not in FOV_WINDOW_CELLS:
        fov_control = 'n/a'
    return TrialCondition(
        experiment=config.experiment,
        trial_id=f"{config.experiment}-s{config.seed}-b{block}-t{trial}",
        block=block,
        trial=trial,
        complexity=factors['complexity'],
        feedback=factors.get('feedback', 'immediate'),
        alignment=factors.get('alignment', 'aligned'),
        transform=factors.get('transform', ViewTransform()),
        fov_size=fov_size,
        fov_control=fov_control,
        tiles=tiles,
        positions=positions,
        figure=figure,
    )


def build_schedule(config: StudyConfig) -> List[TrialCondition]:
    """Build the ordered trials for one agent pair.

    Each block holds one within-pair condition; block order is shuffled with the
    seed. Targets depend only on the seed and the trial's place in the schedule.
    """
    config.validate()
    rng = random.Random(f"schedule:{config.experiment}:{config.seed}")
    per_block = config.resolved_trials_per_block
    trials: List[TrialCondition] = []

    if config.experiment == 'rotation':
        cells = [(a, f) for a in ALIGNMENTS for f in FEEDBACK_MODES]
        rng.shuffle(cells)
        # One transform for the whole pair, as in the original study.
        rotated = ViewTransform(rng.choice(FLIPS), rng.choice(ROTATION_DEGREES))
        for block, (alignment, feedback) in enumerate(cells, start=1):
            transform = rotated if alignment == 'rotated' else ViewTransform()
            for trial in range(1, per_block + 1):
                trials.append(_trial(
                    config, block, trial, complexity=config.complexity,
                    alignment=alignment, feedback=feedback, transform=transform, pair_transform=rotated))
    else:
        cells = [(size, complexity) for size in FOV_SIZES for complexity in config.complexities]
        rng.shuffle(cells)
        rotated = config.fov_alignment == 'rotated'
        rotation = {'alignment': 'rotated', 'transform': FOV_ROTATION, 'pair_transform': FOV_ROTATION} if rotated else {}
        for block, (size, complexity) in enumerate(cells, start=1):
            for trial in range(1, per_block + 1):
                trials.append(_trial(
                    config, block, trial, complexity=complexity,
                    fov_size=size, fov_control=config.fov_control, **rotation))
    return trials
