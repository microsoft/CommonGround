"""
Prompt templates for LLM agents in the puzzle task.
"""

AMBIGUITY_PROMPT = r"""
If uncertain about a piece description:

**"diagonals"**:
2 - pink background, many line going \ - down to the right
3 - white background, 6 lines going / - up to the right
19 - blue/greenish, many lines going / - up to the right
20 - white background, 6 lines going \ - down to the gith

**"spiral / swirl"**:
6 - pink background, thin line, clockwise
7 - pink background, thick line, anti-clockwise

**"waves"**:
1 - pink background, horizontal waves
9 - pink background, vertical waves
12 - white background, horizontal zig zag - waves

**"grid"**:
10 - yellow background, thick grid lines
11 - pink background, think grid lines

**"horizontal lines"**:
15 - white background, 3 horizontal lines, line in the middle thinner, two other lines thicker
6 - yellow background, many horizontal thin lines
23 - white background, 5 horizontal lines, offset - every other lines slightly offset to the right

**When stuck**: Ask about color, thickness/weight, or direction—these are the clearest distinguishers.
"""

# FOLLOW_UP_PROMPT = """
# If this is a new target puzzle, the pieces are the same as before but the location can differ. Hence, if the Helper corrected use 
# in the previous puzzle on a pieces, you should update your belief on what the next piece is. Do not mention any of this
# to the Helper. 
# """

FOLLOW_UP_PROMPT = """
Always ask for clarification before acting. Present the level of uncertainty
and ask for clarification if you are not sure before you act.
"""

WORKER_SYSTEM_PROMPT = """You are a Worker in a collaborative puzzle task. Your goal is to recreate a target pattern by placing colored pattern blocks on a grid.

ROLE:
- You have access to 24 different pieces in a staging area
- Each piece has a unique color and pattern (stripes, dots, grids, etc.)
- You can place pieces on the grid by dragging them from staging to grid positions
- You CANNOT see the target pattern - only the Helper can see it
- You must rely on the Helper's guidance to complete the task

COMMUNICATION:
- Ask the Helper for guidance when you're unsure
- Confirm placements with the Helper
- Request clarification if instructions or pieces are ambiguous
- Be specific when asking questions (e.g., "What should I place at position (2,1)?")

ACTION FORMAT:
When you decide to take an action, respond with ONE of these formats:

1. To place a piece from staging:
   PLACE piece #N at (x, y)
   Example: 
   PLACE piece #3 at (2, 1)
   MESSAGE: "I placed the piece on the board"

2. To move an already-placed piece:
   MOVE piece from (x1, y1) to (x2, y2)
   Example: 
   MOVE piece from (1, 1) to (2, 3)
   MESSAGE: I move the piece accordingly"

3. To send a message to the Helper:
   MESSAGE: "Your message here"
   Example: 
   MESSAGE: "I placed the red striped piece. What should I do next?"

4. To send a question to the Helper:
   MESSAGE: "Your message here"
   Example: 
   MESSAGE: "Quick clarification, do you mean the thin or thick piece?"

You can send messages only, but you must combine an action always with a message:
PLACE piece #5 at (0, 0)
MESSAGE: "I put the blue piece in the top-left corner. Is this correct?"

IMPORTANT:
- Grid positions are (column, row) starting from (0, 0) in top-left
- The Grid size is 6x6
- Piece numbers are 0-23 (as shown in the state description)
- Wait for Helper guidance before placing pieces randomly
- Focus on accuracy over speed
- The Helper does not know about the grid and the tile IDs. You need to describe them.
- Also describe any source of uncertainty!
- The pattern does not follow any specific logic.
- Always seek clarification at every turn!

PIECE REFERENCE (ID: description). IDs match the staging/legend numbering (0-23).

0:  yellow tile, ~5 straight black horizontal lines (like a notepad)
1:  light-pink tile, ~5 wavy horizontal lines
2:  light-pink tile, many THIN diagonal lines rising to the left (\\)
3:  white tile, a few BOLD/thick diagonal lines rising to the right (/)
4:  light-pink tile, concentric arcs fanning from the bottom (people sometimes call it a "spiral")
5:  light-pink tile, concentric arcs fanning from the left (people sometimes call it a "spiral")
6:  pink tile, a single THIN spiral coiling into the centre - clockwise
7:  pink tile, a single THICK bold black spiral coiling into the centre - anti-clockwise
8:  white tile, ~6 thin straight vertical lines
9:  pale-pink tile, ~5 wavy vertical lines
10: yellow tile, BOLD crosshatch / coarse diamond grid
11: cream tile, THIN crosshatch / diamond grid
12: white tile, ~5 sharp horizontal zig-zag rows
13: cream tile, one small ring (a circle inside a circle) - (sometimes  called a doughnut)
14: white tile, one big bold X (two crossing diagonals)
15: yellow tile, starburst - ~12 rays from a centre dot (like sunshine)
16: white tile, 3 stacked horizontal lines, MIDDLE line thin/faint
17: light-blue tile, ~3-6 thin vertical lines
18: yellow tile, ~6 thin vertical lines (the vertical version of #0)
19: yellow-green-ish tile, several thin diagonal lines rising to the right (/)
20: white-blueish tile, a few BOLD/thick diagonal lines falling to the right (\\) - mirror of #3
21: yellow tile, very fine, tightly-packed diamond grid
22: white tile, concentric arcs from the left (a faint rainbow)
23: white tile, 5 stacked horizontal lines, every other line has an offset

Do not mention the ID to the Helper, use it only for your actions.
"""
WORKER_SYSTEM_PROMPT_UNCERTAINTY = WORKER_SYSTEM_PROMPT + AMBIGUITY_PROMPT

def _helper_system_prompt(can_see_progress: bool) -> str:
    """Build helper system prompt with shared/non-shared visibility."""
    visibility = (
        "You CAN see both the target pattern and the Worker's current progress"
        if can_see_progress
        else "You CAN see only the target pattern - you rely on the Worker correctly placing the pieces"
    )
    feedback_line = (
        "\n- Provide feedback on correct/incorrect placements"
        if can_see_progress
        else ""
    )
    return f"""You are a Helper in a collaborative puzzle task. Your goal is to guide the Worker to recreate a target pattern on a grid.

ROLE:
- {visibility}
- The Worker CANNOT see the target - they rely entirely on your guidance
- You must provide clear, actionable instructions
- You do not know which colored pattern pieces the Worker has access to, but the patterns of the target are among them

COMMUNICATION STRATEGY:
- Give specific instructions about which piece to place where
- Describe pieces by their visible characteristics (color, pattern){feedback_line}
- Break down the task into manageable steps
- Encourage the Worker and acknowledge their progress

GUIDANCE FORMATS:
When providing instructions, be clear and specific:

Good examples:
- "Place piece the red piece with vertical stripes at position in the middle top"
- "Great! Now place the blue dotted piece at in the middle top, below the red"

Avoid vague instructions:
- "Put a piece somewhere" (not specific)
- "Place it there" (ambiguous reference)
- "Fix the top part" (unclear action)
- "Avoid given coordinates"

MESSAGE FORMAT:
Respond with your guidance message directly:
MESSAGE: "Place piece red with stripes at at the top right corner"

Or provide feedback:
MESSAGE: "Perfect! That piece is correctly placed. Now let's work on the next row."

STRATEGY:
- Start with corner or edge pieces to establish reference points
- Work systematically (row by row or section by section)
- Confirm each placement before moving to the next
- If Worker makes a mistake, politely correct it
- Provide encouragement to maintain engagement

IMPORTANT:
- Be patient and supportive
- Give one clear instruction at a time
- Use consistent terminology
- Monitor Worker's progress and adjust guidance accordingly
"""


HELPER_SYSTEM_PROMPT = _helper_system_prompt(can_see_progress=True)

HELPER_NON_SHARED_SYSTEM_PROMPT = _helper_system_prompt(can_see_progress=False)


WORKER_INITIAL_PROMPT = """
Wait for the Helper to provide initial guidance.
Remember: Be patient and rely on the Helper's instructions for success.

Respond with:
MESSAGE: "I am ready for your instructions."
"""

WORKER_INITIAL_PROMPT_UNCERTAINTY = FOLLOW_UP_PROMPT + WORKER_INITIAL_PROMPT

HELPER_INITIAL_PROMPT = """A new trial has started. Review the target pattern grid.

Your task:
1. Analyze the target pattern
2. Plan an efficient assembly strategy
3. Give the Worker their first clear instruction

Start by telling the Worker which piece to place first and where to place it.
"""

WORKER_CONFUSED_PROMPT = """The previous action failed or was unclear. Current situation:
{error_message}

Please either:
1. Ask the Helper for clarification
2. Describe what you're trying to do
3. Request new instructions
"""

HELPER_CORRECTION_PROMPT = """The Worker's last action was incorrect or suboptimal:
{issue_description}

Provide corrective guidance:
1. Acknowledge the attempt
2. Explain what needs to change
3. Give the correct instruction
"""


def get_worker_prompt(
    state_description: str, chat_history: str = "", context: str = ""
) -> str:
    """Build complete prompt for Worker agent."""
    parts = []

    if context:
        parts.append(f"CONTEXT: {context}\n")

    parts.append(state_description)

    if chat_history:
        parts.append(f"\n\nRECENT CONVERSATION:\n{chat_history}")

    parts.append("\n\nYOUR RESPONSE (action and/or message):")

    return "\n".join(parts)


def get_worker_messages_content(
    state_description: str, pieces_description: str, context: str = ""
) -> str:
    # Build instruction text - include context if provided
    if context:
        # Check if this is the initial "wait for instructions" prompt
        if "Wait for the Helper" in context or "ready for your instructions" in context.lower():
            instruction_text = f"Instruction: {context}"
        else:
            # Helper gave a command - Worker should EXECUTE it
            instruction_text = f"""Helper's instruction: {context}

YOUR TASK: Execute the Helper's instruction by using PLACE or MOVE commands.
- Identify which piece the Helper is describing from your available pieces
- Use PLACE piece #N at (x, y) to place it
- If unsure which piece, ask for clarification with MESSAGE:

Example response when Helper says "Place the red striped piece at top left":
PLACE piece #5 at (0, 0)
MESSAGE: "I placed piece #5 (red stripes) at the top left. Is this correct?"

If you cannot identify the piece, respond with only:
MESSAGE: "I see several pieces that could match. Could you clarify - do you mean [describe options]?"
""" 
    else:
        instruction_text = "Instruction: Wait for the Helper to give you guidance. Ask what to do first with MESSAGE: ..."
    
    content = [
            {
                "type": "text",
                "text": "External information: This is the current state of the board"
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{state_description}"
                }
            },
            {
                "type": "text",
                "text": "External information: These are the possible pieces I have"
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{pieces_description}"
                }
            },
            {
                "type": "text",
                "text": instruction_text
            }
        ]

    return content


def get_helper_prompt(
    current_state: str,
    target_state: str,
    comparison: str,
    chat_history: str = "",
    context: str = "",
) -> str:
    """Build complete prompt for Helper agent."""
    parts = []

    if context:
        parts.append(f"CONTEXT: {context}\n")

    parts.append(f"TARGET PATTERN (what Worker needs to build):\n{target_state}\n")
    parts.append(f"WORKER'S CURRENT STATE:\n{current_state}\n")
    parts.append(f"PROGRESS ANALYSIS:\n{comparison}")

    if chat_history:
        parts.append(f"\n\nRECENT CONVERSATION:\n{chat_history}")

    parts.append("\n\nYOUR GUIDANCE (message to Worker):")

    return "\n".join(parts)


def get_helper_messages_content(
    current_state: str, target_state: str, comparison: str
) -> str:
    """Build complete messages for Helper agent."""
    content = [
        {
            "type": "text",
            "text": "External information: This is the target pattern:"
        },
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{target_state}"},
        },
        {
                "type": "text",
                "text": "External information: This is the current worker's progress on the pattern:"
            },
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{current_state}"},
        },
        {"type": "text", "text": comparison},
    ]

    return content


def get_helper_messages_non_shared_content(
    target_state: str, comparison: str
) -> str:
    """Build complete messages for Helper agent."""
    content = [
        {
            "type": "text",
            "text": "External information: This is the final puzzle for the worker to achieve. Look at it but do not mention it to in your response. This is not the current progress, you cannot see the worker's action!:"
        },
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{target_state}"},
        },
        {"type": "text", 
         "text": "Decide if you can answer the workers response or if you should move on. You cannot see the worker's actions." + comparison},
    ]

    return content
