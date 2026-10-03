"""Learning progress. Updated only from real challenge outcomes (see core/learning_engine.py)."""
from dataclasses import dataclass, field

CONCEPTS = ("sequence", "conditions", "loops")
CONCEPT_LABELS = {"sequence": "Sequence", "conditions": "Conditions", "loops": "Loops"}


@dataclass
class ConceptProgress:
    introduced: bool = False
    attempts: int = 0
    solved: bool = False
    hints_used: int = 0
    python_unlocked: bool = False
    attempts_to_solve: int = 0  # attempts it took when first solved (0 = not solved yet)
    hints_at_solve: int = 0     # hints viewed by the time it was first solved


def _fresh() -> dict:
    return {c: ConceptProgress().__dict__.copy() for c in CONCEPTS}


@dataclass
class LearningProgress:
    concepts: dict = field(default_factory=_fresh)
