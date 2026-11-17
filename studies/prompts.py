"""System prompts for the visual-information studies, built from a trial's condition.

They deliberately omit the standard Worker prompt's piece-description table and
the Helper's generated "move it left/up" hints, either of which would give the
agents a shared vocabulary or aligned directions the conditions take away.
"""
from .conditions import GRID_SIZE, LOOKS_PER_TURN, TrialCondition

WINDOW_NAMES = {'small': 'a one-cell window (the size of a single piece)',
                'large': 'a 2x2-cell window (the size of four pieces)'}


def _picture_note(trial: TrialCondition, role: str) -> str:
    """For circle-and-stem trials: the pieces form one picture, without saying which picture."""
    if trial.figure is None:
        return ''
    if role == 'worker':
        return ("\n- The target is one simple picture drawn across neighbouring cells. Each piece is one cell "
                "of the picture, so strokes on neighbouring pieces continue from one piece to the next. "
                "Pieces cannot be turned: each is placed exactly as it appears in the staging image.")
    return ("\n- The target is one simple picture drawn across neighbouring cells, and each piece is one cell "
            "of it. The Worker cannot turn pieces: each is placed exactly as the Worker sees it.")


def _worker_view_notes(trial: TrialCondition, disclose: bool) -> list:
    notes = ["The Helper never sees your staging area or your unplaced pieces, only your board."]
    if trial.fov_size == 'full':
        notes.append("The Helper can see your whole board.")
    elif trial.fov_size == 'none':
        notes.append("The Helper cannot see your board at all. Tell them what you do.")
    else:
        notes.append(f"The Helper can see only {WINDOW_NAMES[trial.fov_size]} of your board. "
                     "A red frame on your board image marks the part they can see.")
        notes.append({
            'auto': "The window follows your cursor: it sits at the cell where you last placed, moved, "
                    "removed or pointed.",
            'worker': "You decide where the window is.",
            'helper': "The Helper decides where to look; only the Helper can move the window.",
        }[trial.fov_control])
    if trial.feedback == 'snapshot':
        notes.append("The Helper only sees your board when you send a snapshot, and the snapshot "
                     "shows the board as it was when you sent it.")
    note = orientation_note(trial, 'worker', disclose)
    if note:
        notes.append(note)
    return notes


def orientation_note(trial: TrialCondition, role: str, disclose: bool) -> str:
    """The statement of whether the two views share an orientation.

    Definite but unspecific: a rotated trial says the views are mirrored and
    rotated without saying how, so the agents still have to negotiate a shared
    frame. It is used in the system prompt and repeated every turn. Empty when
    disclosure is off, and in aligned field-of-view trials, whose views never rotate.
    """
    if not disclose or (trial.experiment != 'rotation' and trial.transform.is_identity):
        return ''
    if trial.transform.is_identity:
        if role == 'worker':
            return ("The Helper sees your board in the same orientation as you do, so left, right, "
                    "above and below mean the same to both of you.")
        return ("You see the target and the Worker's board in the same orientation as the Worker, "
                "so left, right, above and below mean the same to both of you.")
    if role == 'worker':
        return ("The Helper's display is mirrored and rotated relative to yours, so left, right, above "
                "and below do not mean the same to both of you. Agree on a shared way to refer to places.")
    return ("Your views of the target and of the Worker's board are mirrored and rotated relative to the "
            "Worker's, so left, right, above and below do not mean the same to both of you. "
            "Agree on a shared way to refer to places.")


def _worker_extra_actions(trial: TrialCondition) -> list:
    actions = []
    if trial.window_cells and trial.fov_control == 'auto':
        actions.append("POINT at (x, y)  - move your cursor, and so the Helper's window, without moving a piece")
    if trial.window_cells and trial.fov_control == 'worker':
        actions.append("SHOW WINDOW at (x, y)  - put the top-left cell of the Helper's window at (x, y)")
    if trial.feedback == 'snapshot':
        actions.append("SEND SNAPSHOT  - send the Helper a picture of your board as it is after this turn's actions")
    return actions


def build_worker_prompt(trial: TrialCondition, disclose: bool = True) -> str:
    extra = _worker_extra_actions(trial)
    extra_text = ''.join(f"\n{action}" for action in extra)
    view_text = '\n'.join(f"- {note}" for note in _worker_view_notes(trial, disclose))
    pieces, used = trial.piece_count, len(trial.tiles)
    return f"""You are the Worker in a collaborative puzzle task. Rebuild a target arrangement on a {GRID_SIZE}x{GRID_SIZE} grid using the pieces in your staging area.

ROLE
- You have {pieces} pieces, shown in the staging image and numbered 0-{pieces - 1}. The numbers are only for your own actions: the Helper cannot see your pieces or their numbers, so never write a piece number (such as #3) in a MESSAGE. Describe pieces to the Helper in words.
- The target uses {used} different pieces, placed next to one another on the grid.{_picture_note(trial, 'worker')}
- You CANNOT see the target. Only the Helper can. Rely on their guidance and ask when anything is unclear.
{view_text}

YOUR BOARD
- Your board image always shows exactly where your pieces are. Check it before every MOVE or REMOVE.
- The column and row numbers on your board are only for you; the Helper cannot see them. If the Helper mentions coordinates or a position, find the cell on your own board image. Never copy the Helper's numbers into an action.
- If an action is rejected, look at your board image again instead of repeating the same action.

ACTIONS (one per line; always combine actions with a MESSAGE)
PLACE piece #N at (x, y)
MOVE piece from (x1, y1) to (x2, y2)
REMOVE piece from (x, y){extra_text}
MESSAGE: "what you want to tell the Helper"

Grid positions are (column, row), numbered on your board image, counted from (0, 0) at the top-left. You may send a MESSAGE without an action.
Example:
PLACE piece #3 at (2, 1)
MESSAGE: "I placed the piece you described. Is that right?"
"""


def _helper_board_text(trial: TrialCondition, human: bool = False) -> list:
    notes = ["The second image shows the Worker's board: the 6x6 grid where the Worker places pieces."]
    if trial.fov_size == 'full':
        notes.append("You can see the Worker's whole board.")
    elif trial.fov_size == 'none':
        notes.append("You cannot see the Worker's board (it appears black). You only know what the Worker tells you.")
    else:
        notes.append(f"You can see only {WINDOW_NAMES[trial.fov_size]} of the Worker's board; "
                     "everything else appears black, which means unseen, not empty.")
        helper_control = ("Only you can move your window, with the LOOK buttons, which use the column letters (A-F) "
                          "and row numbers (1-6) shown around the board image. " if human else
                          "Only you can move your window, with the LOOK action, using the column letters (A-F) and "
                          "row numbers (1-6) around the board image. ")
        notes.append({
            'auto': "The window follows the Worker's cursor, which is where they last placed, moved, removed or pointed.",
            'worker': "The Worker decides where your window is.",
            'helper': helper_control + "The Worker cannot move it, so never ask the Worker to look somewhere.",
        }[trial.fov_control])
    if trial.feedback == 'snapshot':
        notes.append("You only see the Worker's board when they send a snapshot; between snapshots the picture "
                     "does not change.")
    return notes


def _helper_pieces_text(trial: TrialCondition) -> str:
    return (f"You CANNOT see the Worker's pieces. The Worker keeps its {trial.piece_count} pieces off the board, "
            "in a staging area that is never shown to you; no image or snapshot will ever show them. The Worker "
            "numbers them for its own use only, and you do not know which number is which piece, so never ask "
            "for or use piece numbers. Describe what each target cell should look like, and describe places "
            "relative to the board edges or to other pieces.")


def build_helper_prompt(trial: TrialCondition, disclose: bool = True) -> str:
    view_text = '\n'.join(f"- {note}" for note in _helper_board_text(trial))
    note = orientation_note(trial, 'helper', disclose)
    rotated = f"\n- {note}" if note else ""
    helper_window = bool(trial.window_cells) and trial.fov_control == 'helper'
    check = ""
    if trial.fov_size != 'full':
        check = ("\n- Only call a piece correct if you can see it. A cell you cannot see may hold anything"
                 + (", so LOOK there first." if helper_window else "."))
    look = ""
    if helper_window:
        times = 'once' if LOOKS_PER_TURN == 1 else f'{LOOKS_PER_TURN} times'
        look = ("\nLOOK at C3  - move your window so its top-left cell is at column C, row 3.\n"
                f"You can LOOK {times} per turn, so choose where to look carefully. "
                "Write LOOK on its own line, outside the MESSAGE. After a LOOK you see the new view before anything "
                "is sent to the Worker, and any MESSAGE in the same reply is not sent, so look first and write your "
                "message afterwards.")
    return f"""You are the Helper in a collaborative puzzle task. Guide the Worker to rebuild the target arrangement you can see on a {GRID_SIZE}x{GRID_SIZE} grid.

ROLE
- The first image is the target. The Worker CANNOT see it and relies entirely on your guidance.
{view_text}{rotated}
- {_helper_pieces_text(trial)}
- The target uses {len(trial.tiles)} pieces.{_picture_note(trial, 'helper')}

COMMUNICATION
- Give one clear instruction at a time and check that it was understood.
- Say when something is correct or needs fixing.{check}
- Never tell the Worker the puzzle is finished. When you believe it is, write DONE instead (see below).

ACTIONS
MESSAGE: "what you want to tell the Worker"{look}
DONE  - declare the puzzle finished. Write DONE on its own line. The game checks the Worker's board: if it matches the target the trial ends; otherwise you and the Worker are told it is not finished yet.
"""


WORKER_FIRST_TURN = (
    "Wait for the Helper to give you guidance. Reply with:\n"
    'MESSAGE: "I am ready for your instructions."'
)
HELPER_FIRST_TURN = "A new trial has started. Study the target and give the Worker the first instruction."


def worker_turn_instruction(helper_message: str) -> str:
    return (f"Helper's message: {helper_message}\n\n"
            "Carry out the Helper's instruction with the actions above and reply with a MESSAGE. "
            "If you are not sure which piece or place they mean, ask a clarifying question instead.")


def helper_turn_instruction(worker_message: str) -> str:
    return f"Worker's message: {worker_message}\n\nRespond to the Worker with a MESSAGE."


def build_human_helper_instructions(trial: TrialCondition, disclose: bool = True) -> list:
    """The Helper's instructions for a person: the AI Helper's condition notes, with buttons for actions."""
    notes = [f"You are the Helper. The Worker is an AI agent: it cannot see the target and rebuilds it on a "
             f"{GRID_SIZE}x{GRID_SIZE} grid from your messages. The first image is the target."]
    notes += _helper_board_text(trial, human=True)
    note = orientation_note(trial, 'helper', disclose)
    if note:
        notes.append(note)
    notes.append(_helper_pieces_text(trial))
    notes.append(f"The target uses {len(trial.tiles)} pieces.{_picture_note(trial, 'helper').replace(chr(10) + '- ', ' ')}")
    notes.append("Give one clear instruction at a time. Each message you send ends your turn; the Worker then "
                 "acts and replies.")
    if trial.fov_size != 'full':
        notes.append("Only call a piece correct if you can see it.")
    if trial.window_cells and trial.fov_control == 'helper':
        times = 'once' if LOOKS_PER_TURN == 1 else f'{LOOKS_PER_TURN} times'
        notes.append(f"You can LOOK {times} per turn, before you send your message.")
    notes.append("When you believe the puzzle is finished, press DONE: the game checks the Worker's board. "
                 "A trial also ends as soon as the board matches the target.")
    return notes
