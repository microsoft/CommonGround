"""
Shared constants and utility functions for both GUI and web versions of the puzzle.
This file has no GUI dependencies and can be safely imported in headless environments.
"""
import math
from PIL import Image, ImageDraw

GRID_SIZE = 6  # 6x6 grid
PIECE_SIZE = 60  # Size of each grid cell
DELAY_SECONDS = 3  

# Palette indices from tile_pattern_creator groups
GROUP_1_PALETTE_INDICES = [i for i in range(0, 8)]#[0, 2, 7, 10, 14, 16, 19, 20]
GROUP_2_PALETTE_INDICES = [i for i in range(8, 16)]#[3, 5, 12, 13, 17, 18, 22, 23]
GROUP_3_PALETTE_INDICES = [i for i in range(16, 24)]#[1, 4, 6, 8, 9, 11, 15, 21]
PALETTE_INDEX_ORDER = GROUP_1_PALETTE_INDICES + GROUP_2_PALETTE_INDICES + GROUP_3_PALETTE_INDICES

NUM_PIECES = len(PALETTE_INDEX_ORDER)
MIN_TARGET_PIECES = 4  # Minimum pieces in target
MAX_TARGET_PIECES = 8  # Maximum pieces in target

# Tile patterns from tile_pattern_creator.py - all 24 patterns from groups 1, 2, and 3
TILE_PATTERNS = [
    ("#E8E89A", "horizontal_lines"),          # Old Palette index 0
    ("#FFE4E1", "horizontal_wavy"),           # Palette index 2
    ("#FFE4E1", "diagonal_lines_1"),          # Palette index 7
    ("#FFFFFF", "diagonal_thick_2"),          # Palette index 10
    ("#FFF0F5", "concentric_arcs"),           # Palette index 14
    ("#FFF0F5", "concentric_left_straight"),  # Palette index 16
    ("#FFF0F5", "spiral_lines"),              # Palette index 19
    ("#FFF0F5", "spiral_lines_ccw"),          # Palette index 20
    ("#FFFFFF", "vertical_lines"),             # Palette index 3
    ("#FFF0F5", "vertical_curved"),            # Palette index 5
    ("#E8E89A", "crosshatch_loose"),           # Palette index 12
    ("#FAF0E6", "diagonal_crosshatch"),        # Palette index 13
    ("#F5F5F5", "wave_pattern"),               # Palette index 17
    ("#FFFAF0", "nested_curves"),              # Palette index 18
    ("#FFF5EE", "converging_lines"),           # Palette index 22
    ("#E8E89A", "radiating_lines"),            # Palette index 23
    ("#FFFFFF", "horizontal_thick_thin"),      # Palette index 1
    ("#E0FFFF", "vertical_thick_thin"),        # Palette index 4
    ("#E8E89A", "vertical_irregular"),         # Palette index 6
    ("#F0FFF0", "diagonal_lines_2"),           # Palette index 8
    ("#FFFFFF", "diagonal_thick_1"),           # Palette index 9
    ("#E8E89A", "crosshatch_tight"),           # Palette index 11
    ("#FFFFFF", "concentric_arcs_left"),       # Palette index 15
    ("#FFFFFF", "parallel_offset"),            # Palette index 21
]

# Mapping from original palette index to new tile index for puzzle configs
PALETTE_TO_TILE_INDEX = {palette_idx: idx for idx, palette_idx in enumerate(PALETTE_INDEX_ORDER)}

def draw_tile_pattern_shapes(draw_func, pattern, x1, y1, x2, y2):
    """Universal pattern drawing function that works for both canvas and PIL."""
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    size = x2 - x1
    spacing = size / 6
    
    # Horizontal line patterns
    if pattern == "horizontal_lines":
        for i in range(6):
            y = y1 + i * spacing
            draw_func('line', [x1, y, x2, y], fill="black", width=1)
    
    elif pattern == "horizontal_thick_thin":
        for i in range(4):
            y = y1 + i * size / 3
            width = 3 if i % 2 == 0 else 1
            draw_func('line', [x1, y, x2, y], fill="black", width=width)
    
    elif pattern == "horizontal_wavy":
        for i in range(5):
            y_base = y1 + (i + 1) * size / 6
            for j in range(9):
                x_start = x1 + j * size / 8
                x_end = x1 + (j + 1) * size / 8
                amp = size / 20
                y_start = min(y2 - 1, max(y1 + 1, y_base + math.sin(j * 0.8) * amp))
                y_end = min(y2 - 1, max(y1 + 1, y_base + math.sin((j + 1) * 0.8) * amp))
                draw_func('line', [x_start, y_start, x_end, y_end], fill="black", width=1)
    
    elif pattern == "horizontal_irregular":
        positions = [0.1, 0.25, 0.35, 0.6, 0.75, 0.9]
        for pos in positions:
            y = y1 + pos * size
            draw_func('line', [x1, y, x2, y], fill="black", width=1)
    
    # Vertical line patterns
    elif pattern == "vertical_lines":
        for i in range(6):
            x = x1 + i * spacing
            draw_func('line', [x, y1, x, y2], fill="black", width=1)
    
    elif pattern == "vertical_thick_thin":
        for i in range(4):
            x = x1 + i * size / 3
            # width = 3 if i % 2 == 0 else 1
            draw_func('line', [x, y1, x, y2], fill="black", width=1)
    
    elif pattern == "vertical_curved":
        for i in range(5):
            x_base = x1 + (i + 1) * size / 6
            for j in range(9):
                y_start = y1 + j * size / 8
                y_end = y1 + (j + 1) * size / 8
                amp = size / 20
                x_start = min(x2 - 1, max(x1 + 1, x_base + math.sin(j * 0.8) * amp))
                x_end = min(x2 - 1, max(x1 + 1, x_base + math.sin((j + 1) * 0.8) * amp))
                draw_func('line', [x_start, y_start, x_end, y_end], fill="black", width=1)
    
    elif pattern == "vertical_irregular":
        positions = [0.15, 0.3, 0.45, 0.55, 0.7, 0.85]
        for pos in positions:
            x = x1 + pos * size
            draw_func('line', [x, y1, x, y2], fill="black", width=1)
    
    # Diagonal line patterns
    elif pattern == "diagonal_lines_1":
        for i in range(-6, 7):
            offset = i * spacing
            draw_func('line', [x1, y1 + offset, x2, y2 + offset], fill="black", width=1)
    
    elif pattern == "diagonal_lines_2":
        for i in range(-6, 7):
            offset = i * spacing
            draw_func('line', [x1, y2 - offset, x2, y1 - offset], fill="black", width=1)
    
    elif pattern == "diagonal_thick_1":
        for i in range(-5, 6, 2):
            offset = i * spacing
            draw_func('line', [x1, y1 + offset, x2, y2 + offset], fill="black", width=2)
    
    elif pattern == "diagonal_thick_2":
        for i in range(-5, 6, 2):
            offset = i * spacing
            draw_func('line', [x1, y2 - offset, x2, y1 - offset], fill="black", width=2)
    
    # Crosshatch patterns
    elif pattern == "crosshatch":
        for i in range(-6, 7):
            offset = i * spacing
            draw_func('line', [x1, y1 + offset, x2, y2 + offset], fill="black", width=1)
            draw_func('line', [x1, y2 - offset, x2, y1 - offset], fill="black", width=1)
    
    elif pattern == "crosshatch_loose":
        for i in range(-4, 5, 2):
            offset = i * spacing
            draw_func('line', [x1, y1 + offset, x2, y2 + offset], fill="black", width=2)
            draw_func('line', [x1, y2 - offset, x2, y1 - offset], fill="black", width=2)
    
    elif pattern == "diagonal_crosshatch":
        for i in range(-5, 6, 2):
            offset = i * spacing
            draw_func('line', [x1, y1 + offset, x2, y2 + offset], fill="black", width=1)
            draw_func('line', [x1, y2 - offset, x2, y1 - offset], fill="black", width=1)
    
    # Grid pattern
    elif pattern == "grid":
        for i in range(1, 6):
            pos = i * spacing
            draw_func('line', [x1, y1 + pos, x2, y1 + pos], fill="black", width=1)
            draw_func('line', [x1 + pos, y1, x1 + pos, y2], fill="black", width=1)
    
    # Concentric patterns
    elif pattern == "concentric_circles":
        for i in range(1, 6):
            radius = i * spacing / 2
            bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
            draw_func('ellipse', bbox, outline="black", width=1)
    
    elif pattern == "concentric_squares":
        for i in range(1, 6):
            offset = i * spacing / 2
            bbox = [cx - offset, cy - offset, cx + offset, cy + offset]
            draw_func('rectangle', bbox, outline="black", width=1)
    
    elif pattern == "concentric_arcs":
        for i in range(1, 6):
            radius = i * spacing / 2
            bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
            draw_func('arc', bbox, start=0, end=180, outline="black", width=1)
    
    elif pattern == "concentric_left_straight":
        for i in range(1, 6):
            radius = i * spacing / 2
            bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
            draw_func('arc', bbox, start=90, end=270, outline="black", width=1)
    
    # Spiral patterns
    elif pattern == "spiral_lines":
        num_points = 50
        for i in range(num_points - 1):
            angle = i * math.pi / 12
            radius = (i / num_points) * size / 2
            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle)
            angle_next = (i + 1) * math.pi / 12
            radius_next = ((i + 1) / num_points) * size / 2
            x_next = cx + radius_next * math.cos(angle_next)
            y_next = cy + radius_next * math.sin(angle_next)
            draw_func('line', [x, y, x_next, y_next], fill="black", width=1)
    
    elif pattern == "spiral_lines_ccw":
        num_points = 50
        for i in range(num_points - 1):
            angle = -i * math.pi / 12
            radius = (i / num_points) * size / 2
            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle)
            angle_next = -(i + 1) * math.pi / 12
            radius_next = ((i + 1) / num_points) * size / 2
            x_next = cx + radius_next * math.cos(angle_next)
            y_next = cy + radius_next * math.sin(angle_next)
            draw_func('line', [x, y, x_next, y_next], fill="black", width=4)
    
    # Wave patterns
    elif pattern == "wave_pattern":
        amplitude = size / 8
        frequency = 3
        for j in range(4):
            y_base = y1 + (j + 1) * size / 5
            for i in range(20):
                x_start = x1 + i * size / 20
                x_end = x1 + (i + 1) * size / 20
                y_start = y_base + amplitude * math.sin(i * frequency * math.pi / 10)
                y_end = y_base + amplitude * math.sin((i + 1) * frequency * math.pi / 10)
                draw_func('line', [x_start, y_start, x_end, y_end], fill="black", width=1)
    
    elif pattern == "nested_curves":
        for layer in range(3):
            offset = layer * size / 6
            for i in range(10):
                angle = i * math.pi / 5
                x_start = cx + (size / 4 - offset) * math.cos(angle)
                y_start = cy + (size / 4 - offset) * math.sin(angle)
                angle_next = (i + 1) * math.pi / 5
                x_end = cx + (size / 4 - offset) * math.cos(angle_next)
                y_end = cy + (size / 4 - offset) * math.sin(angle_next)
                draw_func('line', [x_start, y_start, x_end, y_end], fill="black", width=1)
    
    # Radiating patterns
    elif pattern == "radiating_lines":
        for i in range(12):
            angle = i * math.pi / 6
            x_end = cx + (size / 2) * math.cos(angle)
            y_end = cy + (size / 2) * math.sin(angle)
            draw_func('line', [cx, cy, x_end, y_end], fill="black", width=1)
    
    elif pattern == "converging_lines":
        points = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
        for point in points:
            draw_func('line', [cx, cy, point[0], point[1]], fill="black", width=1)
    
    # Additional Group 3 patterns
    elif pattern == "crosshatch_tight":
        for i in range(-6, 7):
            offset = i * spacing
            draw_func('line', [x1, y1 + offset, x2, y2 + offset], fill="black", width=1)
            draw_func('line', [x1, y2 - offset, x2, y1 - offset], fill="black", width=1)
    
    elif pattern == "concentric_arcs_left":
        for i in range(1, 6):
            radius = i * spacing / 2
            bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
            draw_func('arc', bbox, start=90, end=270, outline="black", width=1)
    
    elif pattern == "parallel_offset":
        for i in range(5):
            offset_y = i * size / 5
            offset_x = (i % 2) * size / 10
            draw_func('line', [x1 + offset_x, y1 + offset_y, x2 + offset_x, y1 + offset_y], fill="black", width=1)


def generate_pattern_block(size=50, piece_idx=0):
    """Generate a PIL Image for a specific piece/pattern (no Tkinter)."""
    if piece_idx >= len(TILE_PATTERNS):
        piece_idx = piece_idx % len(TILE_PATTERNS)
    
    color, pattern = TILE_PATTERNS[piece_idx]
    
    img = Image.new('RGB', (size, size), color)
    draw = ImageDraw.Draw(img)
    
    def pil_draw_wrapper(shape_type, coords, **kwargs):
        if shape_type == 'line':
            draw.line(coords, **kwargs)
        elif shape_type == 'rectangle':
            draw.rectangle(coords, **kwargs)
        elif shape_type == 'ellipse':
            draw.ellipse(coords, **kwargs)
        elif shape_type == 'arc':
            # PIL's arc uses 'fill' instead of 'outline' and 'width'
            kwargs_arc = kwargs.copy()
            if 'outline' in kwargs_arc:
                kwargs_arc['fill'] = kwargs_arc.pop('outline')
            if 'width' in kwargs_arc:
                kwargs_arc.pop('width')  # PIL arc doesn't support width
            draw.arc(coords, **kwargs_arc)
    
    draw_tile_pattern_shapes(pil_draw_wrapper, pattern, 0, 0, size, size)
    
    return img, color, pattern
