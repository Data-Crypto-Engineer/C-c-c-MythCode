"""Player profile. Preferences are evolving estimates, not fixed types (updated from Phase 4)."""
from dataclasses import dataclass, field

ROLES = ("Wanderer", "Tinkerer", "Healer", "Scout", "Scholar")
STYLES = ("Balanced", "Exploration", "Conversation", "Puzzles", "Building")
PREFERENCE_KEYS = ("exploration", "dialogue", "puzzle", "building", "experimentation")


def _neutral() -> dict:
    return {k: 0.5 for k in PREFERENCE_KEYS}


def _no_confidence() -> dict:
    return {k: 0.0 for k in PREFERENCE_KEYS}


@dataclass
class PlayerProfile:
    name: str = "Traveler"
    role: str = "Wanderer"
    style: str = "Balanced"  # a stated preference only; it does not decide ability or personality
    preferences: dict = field(default_factory=_neutral)
    confidence: dict = field(default_factory=_no_confidence)
    challenge_level: int = 1
