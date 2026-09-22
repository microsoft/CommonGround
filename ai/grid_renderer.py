"""
Grid state serialization and rendering utilities for converting puzzle game state 
to text descriptions and PNG images.
"""
from typing import List, Dict, Tuple, Optional, Any
from PIL import Image, ImageDraw, ImageFont
import io
import base64


    
def describe_piece_simple(piece_idx: int, piece_image: Image.Image = None) -> str:
    """Generate a simple description of a piece."""
    PATTERN_NAMES  = [
            "Evenly spaced horizontal parallel lines",           # Index 0
            "Horizontal lines with wavy undulations",            # Index 1
            "Diagonal lines slanting from upper-left to lower-right",  # Index 2
            "Thick diagonal lines slanting from upper-right to lower-left",  # Index 3
            "Concentric arcs forming semi-circles from bottom",  # Index 4
            "Concentric arcs on left side forming half-circles", # Index 5
            "Clockwise spiral emanating from center",            # Index 6
            "Counter-clockwise spiral emanating from center",    # Index 7
            "Evenly spaced vertical parallel lines",             # Index 8
            "Vertical lines with curved wave-like distortions",  # Index 9
            "Loose crosshatch with widely spaced diagonal lines", # Index 10
            "Medium-spaced diagonal crosshatch pattern",         # Index 11
            "Sinusoidal wave pattern with horizontal orientation", # Index 12
            "Nested curved shapes forming concentric patterns",  # Index 13
            "Lines converging from corners toward center",       # Index 14
            "Lines radiating outward from center point",         # Index 15
            "Horizontal lines alternating between thick and thin", # Index 16
            "Vertical lines alternating between thick and thin", # Index 17
            "Vertical lines with irregular spacing",             # Index 18
            "Diagonal lines slanting from upper-right to lower-left", # Index 19
            "Thick diagonal lines slanting from upper-left to lower-right", # Index 20
            "Tight crosshatch with closely spaced diagonal lines", # Index 21
            "Concentric arcs concentrated on left forming half-circles", # Index 22
            "Parallel horizontal lines with alternating offsets", # Index 23
        ]
    if piece_idx >= len(PATTERN_NAMES):
        return ""
    return PATTERN_NAMES[piece_idx]
        
       

class GridStateSerializer:
    """Serializes grid state into text descriptions."""
    
    def __init__(self, grid_size: int = 6):
        self.grid_size = grid_size
    
    def serialize_grid(
        self, 
        grid: List[List[Optional[int]]], 
        piece_images: Dict[int, Image.Image] = None
    ) -> str:
        """Convert grid state to text description."""
        lines = []
        lines.append("Grid Layout (5x5):")
        lines.append("  " + " ".join([f"Col{i}" for i in range(self.grid_size)]))
        
        for y in range(self.grid_size):
            row_desc = f"Row{y}: "
            cells = []
            for x in range(self.grid_size):
                piece_idx = grid[y][x]
                if piece_idx is None:
                    cells.append("[ empty ]")
                else:
                    if piece_images and piece_idx in piece_images:
                        desc = describe_piece_simple(
                            piece_idx, piece_images[piece_idx]
                        )
                        cells.append(f"[{desc}]")
                    else:
                        cells.append(f"[Piece #{piece_idx + 1}]")
            lines.append(row_desc + " ".join(cells))
        
        return "\n".join(lines)
    
    def serialize_grid_png(
        self,
        grid: List[List[Optional[int]]],
        piece_images: Dict[int, Image.Image] = None,
        cell_size: int = 120,
        border_width: int = 1
    ) -> str:
        """
        Render the grid as a PNG image and return as base64-encoded string.
        
        Args:
            grid: 2D list of piece indices (None for empty cells)
            piece_images: Dictionary mapping piece indices to PIL Images
            cell_size: Size of each grid cell in pixels
            border_width: Width of grid lines (1 for thin grid)
            
        Returns:
            Base64-encoded PNG image string
        """
        # Calculate image dimensions
        img_width = self.grid_size * cell_size
        img_height = self.grid_size * cell_size
        
        # Create new image with white background
        img = Image.new('RGB', (img_width, img_height), 'white')
        draw = ImageDraw.Draw(img)
        
        # Draw grid cells and pieces
        for y in range(self.grid_size):
            for x in range(self.grid_size):
                # Calculate cell boundaries
                x0 = x * cell_size
                y0 = y * cell_size
                x1 = (x + 1) * cell_size
                y1 = (y + 1) * cell_size
                
                # Draw cell background with light gray border
                draw.rectangle([x0, y0, x1, y1], fill='white', outline='gray', width=border_width)
                
                # Draw piece if present
                piece_idx = grid[y][x]
                if piece_idx is not None and piece_images and piece_idx in piece_images:
                    piece_img = piece_images[piece_idx]
                    
                    # Resize piece image to fit in cell with padding
                    piece_size = cell_size - 10  # Leave 5px padding on each side
                    if piece_img.size != (piece_size, piece_size):
                        piece_img_resized = piece_img.resize((piece_size, piece_size), Image.Resampling.LANCZOS)
                    else:
                        piece_img_resized = piece_img
                    
                    # Paste piece image into cell with 5px offset
                    img.paste(piece_img_resized, (x0 + 5, y0 + 5))
                    
                    # Draw black border around piece
                    draw.rectangle([x0, y0, x1, y1], outline='black', width=2)
        
        # Convert image to base64-encoded PNG
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        img_base64 = base64.b64encode(buffer.read()).decode('utf-8')

        return img_base64
    
    def serialize_grids_png(
        self,
        current_grid: List[List[Optional[int]]],
        target_grid: List[List[Optional[int]]],
        piece_images: Dict[int, Image.Image] = None,
        cell_size: int = 120
    ) -> str:
        """
        Render both current worker grid and target grid side by side as a PNG image.
        
        Args:
            current_grid: 2D list of piece indices for current worker progress
            target_grid: 2D list of piece indices for target puzzle
            piece_images: Dictionary mapping piece indices to PIL Images
            cell_size: Size of each grid cell in pixels
            
        Returns:
            Base64-encoded PNG image string
        """
        # Calculate dimensions
        label_margin = 30  # Space for row/column numbers
        grid_width = self.grid_size * cell_size
        grid_height = self.grid_size * cell_size
        spacing = 40  # Space between the two grids
        title_height = 50  # Height for titles above grids
        
        # Total image dimensions (including labels)
        total_width = (grid_width + label_margin) * 2 + spacing
        total_height = grid_height + title_height + label_margin
        
        # Create new image with light gray background
        img = Image.new('RGB', (total_width, total_height), (245, 245, 245))
        draw = ImageDraw.Draw(img)
        
        # Try to load fonts
        try:
            title_font = ImageFont.truetype("arial.ttf", 28)
        except:
            try:
                title_font = ImageFont.truetype("Arial.ttf", 28)
            except:
                title_font = ImageFont.load_default()
        
        try:
            label_font = ImageFont.truetype("arial.ttf", 16)
        except:
            try:
                label_font = ImageFont.truetype("Arial.ttf", 16)
            except:
                label_font = ImageFont.load_default()
        
        # Draw titles
        current_title = "Current Progress"
        target_title = "Target"
        
        # Draw current progress title (centered over left grid)
        try:
            bbox = draw.textbbox((0, 0), current_title, font=title_font)
            text_width = bbox[2] - bbox[0]
        except:
            text_width, _ = draw.textsize(current_title, font=title_font)
        
        current_title_x = label_margin + (grid_width - text_width) // 2
        draw.text((current_title_x, 15), current_title, fill=(51, 51, 51), font=title_font)
        
        # Draw target title (centered over right grid)
        try:
            bbox = draw.textbbox((0, 0), target_title, font=title_font)
            text_width = bbox[2] - bbox[0]
        except:
            text_width, _ = draw.textsize(target_title, font=title_font)
        
        target_title_x = grid_width + label_margin + spacing + label_margin + (grid_width - text_width) // 2
        draw.text((target_title_x, 15), target_title, fill=(51, 51, 51), font=title_font)
        
        # Helper function to draw a grid with row/column numbers
        def draw_grid(grid, x_offset, y_offset):
            # Draw column numbers at top
            for col_idx in range(self.grid_size):
                x = x_offset + label_margin + col_idx * cell_size + cell_size // 2
                y = y_offset + label_margin // 2
                draw.text((x, y), str(col_idx + 1), fill=(51, 51, 51), anchor="mm", font=label_font)
            
            # Draw row numbers on left
            for row_idx in range(self.grid_size):
                x = x_offset + label_margin // 2
                y = y_offset + label_margin + row_idx * cell_size + cell_size // 2
                draw.text((x, y), str(row_idx + 1), fill=(51, 51, 51), anchor="mm", font=label_font)
            
            # Draw grid cells
            for y in range(self.grid_size):
                for x in range(self.grid_size):
                    # Calculate cell boundaries (offset by label_margin)
                    x0 = x_offset + label_margin + x * cell_size
                    y0 = y_offset + label_margin + y * cell_size
                    x1 = x_offset + label_margin + (x + 1) * cell_size
                    y1 = y_offset + label_margin + (y + 1) * cell_size
                    
                    # Draw cell background with border
                    draw.rectangle([x0, y0, x1, y1], fill='white', outline='black', width=2)
                    
                    # Draw piece if present
                    piece_idx = grid[y][x]
                    if piece_idx is not None and piece_images and piece_idx in piece_images:
                        piece_img = piece_images[piece_idx]
                        
                        # Resize piece image to fit in cell with padding
                        piece_size = cell_size - 10
                        if piece_img.size != (piece_size, piece_size):
                            piece_img_resized = piece_img.resize(
                                (piece_size, piece_size), 
                                Image.Resampling.LANCZOS
                            )
                        else:
                            piece_img_resized = piece_img
                        
                        # Paste piece image into cell
                        img.paste(piece_img_resized, (x0 + 5, y0 + 5))
        
        # Draw current progress grid (left side)
        draw_grid(current_grid, 0, title_height)
        
        # Draw target grid (right side)
        draw_grid(target_grid, grid_width + label_margin + spacing, title_height)
        
        # Convert image to base64-encoded PNG
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        img_base64 = base64.b64encode(buffer.read()).decode('utf-8')
        
        return img_base64
    
    def serialize_piece_images_png(
        self,
        piece_images: Dict[int, Image.Image],
        pieces_per_row: int = 5,
        piece_size: int = 100,
        padding: int = 10,
        label_height: int = 30
    ) -> str:
        """
        Create a PNG showing all pieces with their IDs.
        
        Args:
            piece_images: Dictionary mapping piece indices to PIL Images
            pieces_per_row: Number of pieces to display per row
            piece_size: Size of each piece thumbnail in pixels
            padding: Padding between pieces in pixels
            label_height: Height for the ID label under each piece
            
        Returns:
            Base64-encoded PNG image string
        """
        if not piece_images:
            # Return empty 1x1 white image if no pieces
            img = Image.new('RGB', (1, 1), 'white')
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            buffer.seek(0)
            return base64.b64encode(buffer.read()).decode('utf-8')
        
        # Calculate layout
        num_pieces = len(piece_images)
        num_rows = (num_pieces + pieces_per_row - 1) // pieces_per_row
        
        cell_width = piece_size + 2 * padding
        cell_height = piece_size + label_height + 2 * padding
        
        img_width = pieces_per_row * cell_width
        img_height = num_rows * cell_height
        
        # Create image with white background
        img = Image.new('RGB', (img_width, img_height), 'white')
        draw = ImageDraw.Draw(img)
        
        # Try to load a font for labels, fall back to default if unavailable
        try:
            font = ImageFont.truetype("arial.ttf", 20)
        except:
            try:
                font = ImageFont.truetype("Arial.ttf", 20)
            except:
                font = ImageFont.load_default()
        
        # Sort piece indices for consistent ordering
        sorted_pieces = sorted(piece_images.items(), key=lambda x: x[0])
        
        # Draw each piece with its ID
        for idx, (piece_idx, piece_img) in enumerate(sorted_pieces):
            row = idx // pieces_per_row
            col = idx % pieces_per_row
            
            x_offset = col * cell_width + padding
            y_offset = row * cell_height + padding
            
            # Resize piece image if needed
            if piece_img.size != (piece_size, piece_size):
                piece_img_resized = piece_img.resize(
                    (piece_size, piece_size), 
                    Image.Resampling.LANCZOS
                )
            else:
                piece_img_resized = piece_img
            
            # Paste piece image
            img.paste(piece_img_resized, (x_offset, y_offset))
            
            # Draw border around piece
            draw.rectangle(
                [x_offset, y_offset, x_offset + piece_size, y_offset + piece_size],
                outline='black',
                width=2
            )
            
            # Draw ID label below piece
            label_text = f"{piece_idx}"
            
            # Get text bounding box for centering
            try:
                bbox = draw.textbbox((0, 0), label_text, font=font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
            except:
                # Fallback for older PIL versions
                text_width, text_height = draw.textsize(label_text, font=font)
            
            text_x = x_offset + (piece_size - text_width) // 2
            text_y = y_offset + piece_size + 5
            
            draw.text((text_x, text_y), label_text, fill='black', font=font)
        
        # Convert to base64
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        img_base64 = base64.b64encode(buffer.read()).decode('utf-8')
        
        return img_base64
    
    def serialize_staging_area(
        self,
        staging_pieces: List[Tuple[Any, int]],
        piece_images: Dict[int, Image.Image] = None
    ) -> str:
        """Convert staging area pieces to text description."""
        lines = ["Available Pieces in Staging Area:"]
        
        for canvas_id, piece_idx in staging_pieces:
            if piece_images and piece_idx in piece_images:
                desc = describe_piece_simple(
                    piece_idx, piece_images[piece_idx]
                )
                lines.append(f"  - {desc}")
            else:
                lines.append(f"  - Piece #{piece_idx + 1}")
        
        return "\n".join(lines)
    
    def compare_grids(
        self,
        current_grid: List[List[Optional[int]]],
        target_grid: List[List[Optional[int]]],
        piece_images: Dict[int, Image.Image] = None
    ) -> str:
        """
        Generate comprehensive comparison between current and target grids.
        Analyzes absolute correctness, relative positioning, and potential offsets.
        """
        lines = ["Comparison (Current vs Target):"]
        
        # Build position mappings
        target_positions = {}  # piece_id -> (x, y)
        current_positions = {}  # piece_id -> (x, y)
        
        for y in range(self.grid_size):
            for x in range(self.grid_size):
                target_piece = target_grid[y][x]
                current_piece = current_grid[y][x]
                
                if target_piece is not None:
                    target_positions[target_piece] = (x, y)
                if current_piece is not None:
                    current_positions[current_piece] = (x, y)
        
        # 1. Absolutely correct placements (right piece, right position)
        correct_absolute = []
        for piece_id, (tx, ty) in target_positions.items():
            if piece_id in current_positions:
                cx, cy = current_positions[piece_id]
                if cx == tx and cy == ty:
                    correct_absolute.append((piece_id, tx, ty))
        
        # 2. Wrong position but piece exists (calculate offsets)
        wrong_position = []
        for piece_id, (tx, ty) in target_positions.items():
            if piece_id in current_positions:
                cx, cy = current_positions[piece_id]
                if cx != tx or cy != ty:
                    offset_x = cx - tx
                    offset_y = cy - ty
                    wrong_position.append((piece_id, (cx, cy), (tx, ty), offset_x, offset_y))
        
        # 3. Missing pieces (in target but not in current)
        missing_pieces = []
        for piece_id, (tx, ty) in target_positions.items():
            if piece_id not in current_positions:
                missing_pieces.append((piece_id, tx, ty))
        
        # 4. Extra pieces (in current but not in target)
        extra_pieces = []
        for piece_id, (cx, cy) in current_positions.items():
            if piece_id not in target_positions:
                extra_pieces.append((piece_id, cx, cy))
        
        # 5. Detect common offset pattern (if all pieces share similar offset)
        if wrong_position:
            offset_counts = {}
            for _, _, _, dx, dy in wrong_position:
                offset_counts[(dx, dy)] = offset_counts.get((dx, dy), 0) + 1
            
            # Find most common offset
            most_common_offset = max(offset_counts.items(), key=lambda x: x[1])
            offset_dx, offset_dy = most_common_offset[0]
            offset_count = most_common_offset[1]
            
            if offset_count >= len(wrong_position) * 0.5:  # At least 50% share this offset
                lines.append(f"\nDETECTED PATTERN: Most pieces shifted by ({offset_dx:+d}, {offset_dy:+d})")
                lines.append(f"   {offset_count}/{len(wrong_position)} misplaced pieces share this offset")
        
        # Report results
        total_target = len(target_positions)
        total_current = len(current_positions)

        result = {
            "Pieces at wrong positions": len(wrong_position),
            "Missing pieces": len(missing_pieces),
            "Wrong pieces": len(extra_pieces)
        }
        
        # lines.append(f"There are currently {len(extra_pieces)} wrong pieces and {len(wrong_position)} pieces at wrong positions.")
        lines = []# [f"There are currently {len(extra_pieces)} wrong pieces and {len(wrong_position)} pieces at wrong positions."]

        # lines.append(f"   Total pieces in target: {total_target}")
        # lines.append(f"   Total pieces placed: {total_current}")
        # lines.append(f"   Correct positions: {len(correct_absolute)}")
        # lines.append(f"   Pieces at wrong positions: {len(wrong_position)}")
        # lines.append(f"   Pieces at wrong positions: {len(wrong_position)}")
        # lines.append(f"   Missing pieces: {len(missing_pieces)}")
        # lines.append(f"   Wrong pieces: {len(extra_pieces)}")
        
        # # Show correct placements
        # if correct_absolute:
        #     lines.append(f"\nCORRECT PLACEMENTS ({len(correct_absolute)}):")
        #     for piece_id, x, y in correct_absolute[:5]:
        #         piece_desc = PieceDescriptor.describe_piece_simple(
        #             piece_id, piece_images.get(piece_id) if piece_images else None
        #         )
        #         lines.append(f"   Position ({x+1}, {y+1}): {piece_desc}")
        #     if len(correct_absolute) > 5:
        #         lines.append(f"   ... and {len(correct_absolute) - 5} more")
        
        # # Show wrong positions with offsets
        if wrong_position:
            lines.append(f"\nWRONG POSITION ({len(wrong_position)}):")
            for piece_id, (cx, cy), (tx, ty), dx, dy in wrong_position[:5]:
                piece_desc = describe_piece_simple(
                    piece_id, piece_images.get(piece_id) if piece_images else None
                )

                loc_change = "Should be  "
                if dx > 0:
                    loc_change = loc_change + "more to the left"
                if dx < 0:
                    loc_change = loc_change + "more to the right"
                if dy > 0:
                    loc_change = loc_change + " more to the top"
                if dy < 0:
                    loc_change = loc_change + " more down"

                

                lines.append(f"   {piece_desc}:")
                # lines.append(f"      Current: ({cx+1}, {cy+1}) | Target: ({tx+1}, {ty+1}) | Offset: ({dx:+d}, {dy:+d})")
                lines.append(f"      {loc_change}")
            if len(wrong_position) > 5:
                lines.append(f"   ... and {len(wrong_position) - 5} more")
        
        # # Show missing pieces
        # if missing_pieces:
        #     lines.append(f"\nMISSING PIECES ({len(missing_pieces)}):")
        #     for piece_id, tx, ty in missing_pieces[:5]:
        #         piece_desc = PieceDescriptor.describe_piece_simple(
        #             piece_id, piece_images.get(piece_id) if piece_images else None
        #         )
        #         lines.append(f"   {piece_desc} needed at ({tx+1}, {ty+1})")
        #     if len(missing_pieces) > 5:
        #         lines.append(f"   ... and {len(missing_pieces) - 5} more")
        
        # # Show extra pieces
        if extra_pieces:
            lines.append(f"\nWRONG PIECES ({len(extra_pieces)}):")
            for piece_id, cx, cy in extra_pieces[:3]:
                piece_desc = describe_piece_simple(
                    piece_id, piece_images.get(piece_id) if piece_images else None
                )
                lines.append(f"   {piece_desc} (not in target)")
                # lines.append(f"   {piece_desc} at ({cx+1}, {cy+1}) (not in target)")
            if len(extra_pieces) > 3:
                lines.append(f"   ... and {len(extra_pieces) - 3} more")

        if len(extra_pieces) == len(wrong_position) == 0:
            return "Currently no mismatches."
        
        return "\n".join(lines)
    
    def serialize_full_state(
        self,
        work_area: List[List[Optional[int]]],
        staging_pieces: List[Tuple[Any, int]],
        piece_images: Dict[int, Image.Image] = None,
        target_area: List[List[Optional[int]]] = None
    ) -> str:
        """Serialize complete game state."""
        sections = []
        
        sections.append("=== CURRENT STATE ===")
        sections.append(self.serialize_grid(work_area, piece_images))
        sections.append("")
        sections.append(self.serialize_staging_area(staging_pieces, piece_images))
        
        if target_area:
            sections.append("")
            sections.append("=== TARGET PATTERN ===")
            sections.append(self.serialize_grid(target_area, piece_images))
            sections.append("")
            sections.append(self.compare_grids(work_area, target_area, piece_images))
        
        return "\n".join(sections)
