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
    def parse_llm_response(text: str) -> Dict[str, Any]:
        """
        Parse complete LLM response into structured actions.
        Returns dict with 'actions' list and 'message' if present.
        Supports multiple actions and preserves their order in the text.
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
        
        # Sort actions by their position in the text to preserve order
        action_matches.sort(key=lambda x: x[0])
        result['actions'] = [action for pos, action in action_matches]
        
        # Try to parse message
        message = ActionParser.parse_message(text)
        if message:
            result['message'] = message
        
        return result
