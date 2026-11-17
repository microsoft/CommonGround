"""
Parser for converting LLM text outputs into structured puzzle game actions.
"""
import re
from typing import List, Dict, Optional, Any


class ActionParser:
    """Parse LLM text outputs into structured actions."""
    
    @staticmethod
    def parse_place_action(text: str) -> List[Dict[str, Any]]:
        """
        Parse action like: 'PLACE piece 3 at (2, 1)' or 'Place Piece #3 at position (2,1)'
        Returns list of actions: [{'action': 'place', 'piece': 2, 'position': (2, 1)}, ...] (0-indexed)
        """
        results = []
        
        # Pattern to match various formats
        patterns = [
            r'(?:PLACE|place)\s+(?:piece\s*#?|Piece\s*#?)(\d+)\s+(?:at|to)\s+(?:position\s*)?\(?(\d+)\s*,\s*(\d+)\)?',
            r'(?:PUT|put)\s+(?:piece\s*#?|Piece\s*#?)(\d+)\s+(?:at|to|in)\s+(?:position\s*)?\(?(\d+)\s*,\s*(\d+)\)?',
            r'(?:piece\s*#?|Piece\s*#?)(\d+)\s+(?:goes\s+)?(?:at|to|in)\s+\(?(\d+)\s*,\s*(\d+)\)?',
        ]
        
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                piece_num = int(match.group(1))
                x = int(match.group(2))
                y = int(match.group(3))
                results.append({
                    'action': 'place',
                    'piece': piece_num,
                    'position': (x, y)
                })
        
        return results
    
    @staticmethod
    def parse_move_action(text: str) -> List[Dict[str, Any]]:
        """
        Parse action like: 'MOVE piece from (1,1) to (2,3)'
        Returns list of actions: [{'action': 'move', 'from': (1, 1), 'to': (2, 3)}, ...]
        """
        results = []
        
        patterns = [
            r'(?:MOVE|move)\s+(?:piece\s+)?(?:from\s+)?\(?(\d+)\s*,\s*(\d+)\)?\s+(?:to\s+)\(?(\d+)\s*,\s*(\d+)\)?',
        ]
        
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                from_x = int(match.group(1))
                from_y = int(match.group(2))
                to_x = int(match.group(3))
                to_y = int(match.group(4))
                results.append({
                    'action': 'move',
                    'from': (from_x, from_y),
                    'to': (to_x, to_y)
                })
        
        return results
    
    @staticmethod
    def parse_remove_action(text: str) -> List[Dict[str, Any]]:
        """
        Parse action like: 'REMOVE piece from (2,2)' or 'MOVE piece from (2,2) to staging'
        Returns list of actions: [{'action': 'remove', 'position': (2, 2)}, ...]
        """
        results = []
        
        patterns = [
            r'(?:REMOVE|remove)\s+(?:piece\s+)?(?:from\s+)?\(?(\d+)\s*,\s*(\d+)\)?',
            r'(?:MOVE|move)\s+(?:piece\s+)?(?:from\s+)?\(?(\d+)\s*,\s*(\d+)\)?\s+(?:to\s+)?(?:staging|back)',
        ]
        
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                x = int(match.group(1))
                y = int(match.group(2))
                results.append({
                    'action': 'remove',
                    'position': (x, y)
                })
        
        return results
    
    @staticmethod
    def parse_message(text: str) -> Optional[str]:
        """
        Extract all chat messages from LLM response and concatenate them.
        Looks for MESSAGE:, SAY:, or CHAT: prefixes.
        Returns concatenated messages separated by spaces.
        """
        messages = []
        seen_positions = set()
        
        # Pattern to match MESSAGE:/SAY:/CHAT: followed by quoted content
        # This pattern prioritizes quoted strings to avoid duplicates
        quoted_patterns = [
            r'(?:MESSAGE|SAY|CHAT):\s*"([^"]+)"',
            r"(?:MESSAGE|SAY|CHAT):\s*'([^']+)'",
        ]
        
        # First, find all quoted messages and track their positions
        for pattern in quoted_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                message = match.group(1).strip()
                if message and match.start() not in seen_positions:
                    messages.append((match.start(), message))
                    seen_positions.add(match.start())
        
        # If we found quoted messages, use only those
        if messages:
            # Sort by position in text to maintain order
            messages.sort(key=lambda x: x[0])
            return ' '.join([msg for pos, msg in messages])
        
        # Fallback: try unquoted pattern
        unquoted_pattern = r'(?:MESSAGE|SAY|CHAT):\s*([^\n]+?)(?=\s*(?:PLACE|MOVE|REMOVE|$))'
        for match in re.finditer(unquoted_pattern, text):
            message = match.group(1).strip()
            if message:
                messages.append((match.start(), message))
        
        if messages:
            messages.sort(key=lambda x: x[0])
            return ' '.join([msg for pos, msg in messages])
        
        # Final fallback to old patterns for backward compatibility
        fallback_patterns = [
            r'(?:MESSAGE|SAY|CHAT):\s*["\']?(.+)["\']?$',
            r'(?:I (?:will |would )?(?:say|tell|ask)):\s*["\']?(.+)["\']?$',
        ]
        
        for pattern in fallback_patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                return match.group(1).strip()
        
        return None
    
    @staticmethod
    def parse_study_actions(text: str, look_anywhere: bool = False, allow_done: bool = False) -> List[tuple]:
        """
        Parse the extra actions used by the visual-information studies.

        Only commands at the start of a line count, so words inside a MESSAGE
        cannot trigger them. With ``look_anywhere`` (used for the Helper, the only
        role that can LOOK) a LOOK at a labelled cell such as C3 counts anywhere,
        since the Helper often writes it inside its message. With ``allow_done``
        (also the Helper only) a line holding just DONE declares the puzzle finished;
        it must be the whole line, so "tell me when it's done" never counts.
        Returns (position_in_text, action) pairs.
        """
        bullet = r'^[ \t]*(?:[-*][ \t]*)?'
        coords = r'(?:[ \t]+at)?[ \t]*\(?(\d+)[ \t]*,[ \t]*(\d+)\)?'
        found = []
        flags = re.IGNORECASE | re.MULTILINE
        for match in re.finditer(bullet + r'POINT' + coords, text, flags):
            found.append((match.start(), {
                'action': 'point', 'position': (int(match.group(1)), int(match.group(2)))}))
        for match in re.finditer(bullet + r'SEND[ \t]+SNAPSHOT\b', text, flags):
            found.append((match.start(), {'action': 'snapshot'}))
        for match in re.finditer(bullet + r'SHOW[ \t]+(?:WINDOW|VIEW)' + coords, text, flags):
            found.append((match.start(), {
                'action': 'window', 'position': (int(match.group(1)), int(match.group(2)))}))
        look_start = r'\b' if look_anywhere else bullet
        for match in re.finditer(look_start + r'LOOK(?:[ \t]+at)?[ \t]+\**\(?([A-F])([1-6])\b', text, flags):
            column = 'ABCDEF'.index(match.group(1).upper())
            found.append((match.start(), {
                'action': 'look', 'position': (column, int(match.group(2)) - 1)}))
        if allow_done:
            for match in re.finditer(bullet + r'\**DONE\**[ \t]*[.!]?[ \t]*$', text, flags):
                found.append((match.start(), {'action': 'done'}))
        return found

    @staticmethod
    def parse_llm_response(text: str, study_actions: bool = False, look_anywhere: bool = False,
                           allow_done: bool = False) -> Dict[str, Any]:
        """
        Parse complete LLM response into structured actions.
        Returns dict with 'actions' list and 'message' if present.
        Supports multiple actions and preserves their order in the text.
        Set study_actions to also recognise POINT, SEND SNAPSHOT, SHOW WINDOW and LOOK;
        look_anywhere and allow_done are the Helper's options (see parse_study_actions).
        """
        result = {
            'actions': [],
            'message': None,
            'raw_text': text
        }
        
        # Find all actions with their positions in the text
        action_matches = []
        
        # PLACE patterns
        place_patterns = [
            r'(?:PLACE|place)\s+(?:piece\s*#?|Piece\s*#?)(\d+)\s+(?:at|to)\s+(?:position\s*)?\(?(\d+)\s*,\s*(\d+)\)?',
            r'(?:PUT|put)\s+(?:piece\s*#?|Piece\s*#?)(\d+)\s+(?:at|to|in)\s+(?:position\s*)?\(?(\d+)\s*,\s*(\d+)\)?',
        ]
        for pattern in place_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                piece_num = int(match.group(1))
                x = int(match.group(2))
                y = int(match.group(3))
                action_matches.append((match.start(), {
                    'action': 'place',
                    'piece': piece_num,
                    'position': (x, y)
                }))
        
        # REMOVE patterns (check these BEFORE move to avoid conflicts)
        remove_patterns = [
            r'(?:REMOVE|remove)\s+(?:piece\s+)?(?:from\s+)?\(?(\d+)\s*,\s*(\d+)\)?',
            r'(?:MOVE|move)\s+(?:piece\s+)?(?:from\s+)?\(?(\d+)\s*,\s*(\d+)\)?\s+(?:to\s+)?(?:staging|back)',
        ]
        for pattern in remove_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                x = int(match.group(1))
                y = int(match.group(2))
                action_matches.append((match.start(), {
                    'action': 'remove',
                    'position': (x, y)
                }))
        
        # MOVE patterns (regular moves between grid positions)
        move_patterns = [
            r'(?:MOVE|move)\s+(?:piece\s+)?(?:from\s+)?\(?(\d+)\s*,\s*(\d+)\)?\s+(?:to\s+)\(?(\d+)\s*,\s*(\d+)\)?',
        ]
        for pattern in move_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                # Skip if this match overlaps with a remove action
                is_remove = any(
                    abs(match.start() - pos) < 10 and action['action'] == 'remove'
                    for pos, action in action_matches
                )
                if not is_remove:
                    from_x = int(match.group(1))
                    from_y = int(match.group(2))
                    to_x = int(match.group(3))
                    to_y = int(match.group(4))
                    action_matches.append((match.start(), {
                        'action': 'move',
                        'from': (from_x, from_y),
                        'to': (to_x, to_y)
                    }))
        
        if study_actions:
            action_matches.extend(ActionParser.parse_study_actions(text, look_anywhere=look_anywhere,
                                                                   allow_done=allow_done))

        # Sort actions by their position in the text to preserve order
        action_matches.sort(key=lambda x: x[0])
        result['actions'] = [action for pos, action in action_matches]
        
        # Try to parse message
        message = ActionParser.parse_message(text)
        if message:
            result['message'] = message
        
        return result
