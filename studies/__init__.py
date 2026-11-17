"""AI-AI adaptations of the rotation and field-of-view studies.

Based on Gergle, Kraut and Fussell (2013), "Using Visual Information for
Grounding and Awareness in Collaborative Tasks", Human-Computer Interaction
28(1), 1-39 (Experiments 2 and 3). See the README section "Visual-information
studies" for how the original manipulations are mapped onto this app.
"""
from .conditions import (
    EXPERIMENTS,
    StudyConfig,
    TrialCondition,
    ViewTransform,
    build_schedule,
)

__all__ = [
    'EXPERIMENTS',
    'StudyConfig',
    'TrialCondition',
    'ViewTransform',
    'build_schedule',
]
