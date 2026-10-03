"""Learning progress. Updated only from real challenge outcomes (Phase 2)."""
from dataclasses import dataclass, field

CONCEPTS = ("sequence", "conditions", "loops")


@dataclass
class ConceptProgress:
    introduced: bool = False
    attempts: int = 0
    solved: bool = False
    hints_used: int = 0
    python_unlocked: bool = False


def _fresh() -> dict:
    return {c: ConceptProgress().__dict__.copy() for c in CONCEPTS}


@dataclass
class LearningProgress:
    concepts: dict = field(default_factory=_fresh)
