#!/usr/bin/env python3
"""
Random User Generator Script

This script generates random user IDs and tokens with a 50:50 distribution
of system prompts for the CommonGroundChat application.

Usage:
    python generate_users.py [--count COUNT] [--output OUTPUT_FILE]
"""

import json
import random
import hashlib
import argparse
from typing import Dict, Any


def generate_random_user_id() -> str:
    """Generate a random 5-digit user ID."""
    return str(random.randint(10000, 99999))


def generate_random_token() -> str:
    """Generate a random 32-character hexadecimal token."""
    # Generate random bytes and hash them to get a consistent 32-char hex string
    random_bytes = random.getrandbits(128).to_bytes(16, byteorder='big')
    return hashlib.md5(random_bytes).hexdigest()


def generate_users(count: int) -> Dict[str, Dict[str, Any]]:
    """
    Generate a specified number of users with random IDs and tokens.
    
    Args:
        count: Number of users to generate
        
    Returns:
        Dictionary of users in the format expected by user_credentials.json
    """
    users = {}
    system_prompts = ["Default Assistant", "Improved Collaborative Assistant"]
    used_ids = set()
    
    for i in range(count):
        # Generate unique user ID
        user_id = generate_random_user_id()
        while user_id in used_ids:
            user_id = generate_random_user_id()
        used_ids.add(user_id)
        
        # Determine role (most users are participants, some are admins)
        role = "participant" #if random.random() > 0.1 else "admin"
        function = "worker" if i > count//2 else "helper"
        # Create base user data
        user_data = {
            "token": generate_random_token(),
            "role": role,
            "study_id": "123",
            "function": function
        }
        
        # Add system prompt for participants (50:50 distribution)
        if role == "participant":
            user_data["system_prompt"] = system_prompts[i % 2]
        
        users[user_id] = user_data
    
    return users


def save_users_to_file(users: Dict[str, Dict[str, Any]], output_file: str) -> None:
    """Save users to a JSON file."""
    user_credentials = {"users": users}
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(user_credentials, f, indent=2, ensure_ascii=False)
    
    with open(output_file.replace(".json", ".txt"), 'w', encoding='utf-8') as f:
        for k, v in user_credentials["users"].items():
            # print(k, v)
            f.write(v["function"] + ", " + k + "," + v["token"] + "\n")
    
    print(f"Generated {len(users)} users and saved to {output_file}")


def print_distribution_stats(users: Dict[str, Dict[str, Any]]) -> None:
    """Print statistics about the generated users."""
    total_users = len(users)
    participants = sum(1 for user in users.values() if user["role"] == "participant")
    admins = total_users - participants
    
    # Count system prompt distribution
    default_count = sum(1 for user in users.values() 
                       if user.get("system_prompt") == "Default Assistant")
    improved_count = sum(1 for user in users.values() 
                        if user.get("system_prompt") == "Improved Collaborative Assistant")
    
    print("\nGeneration Statistics:")
    print(f"Total users: {total_users}")
    print(f"Participants: {participants}")
    print(f"Admins: {admins}")
    print(f"Default Assistant prompt: {default_count}")
    print(f"Improved Collaborative Assistant prompt: {improved_count}")
    
    if participants > 0:
        default_percentage = (default_count / participants) * 100
        improved_percentage = (improved_count / participants) * 100
        print(f"System prompt distribution among participants:")
        print(f"  Default Assistant: {default_percentage:.1f}%")
        print(f"  Improved Collaborative Assistant: {improved_percentage:.1f}%")


def main():
    """Main function to handle command line arguments and generate users."""
    parser = argparse.ArgumentParser(
        description="Generate random users with tokens and system prompts"
    )
    parser.add_argument(
        "--count", 
        type=int, 
        default=60,
        help="Number of users to generate (default: 10)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="generated_users.json",
        help="Output file name (default: generated_users.json)"
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="Random seed for reproducible results"
    )
    
    args = parser.parse_args()
    
    # Set random seed if provided
    if args.seed:
        random.seed(args.seed)
        print(f"Using random seed: {args.seed}")
    
    # Generate users
    print(f"Generating {args.count} users...")
    users = generate_users(args.count)
    
    # Save to file
    save_users_to_file(users, args.output)
    
    # Print statistics
    print_distribution_stats(users)


if __name__ == "__main__":
    main()
