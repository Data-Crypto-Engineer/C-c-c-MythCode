"""AGENT 5: Logic & Learning.

A thin tracking layer: it RECORDS puzzle outcomes that your deterministic puzzle
engine (core/learning_engine.py) has already judged. It never decides whether an
answer is correct and never runs player code. Python reveals only unlock after a
real success.

NOTE: this module keeps its own plain-dict progress record. Phase 4 will connect
it to your existing Learning Journal structures after I have read those files.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping

ROLE = "Logic & Learning Guide"
GOAL = "Connect solved challenges to the matching real Python idea, accurately."
BACKSTORY = "A patient teacher who reveals code only after the player has earned the idea."

CONCEPTS = ("sequence", "conditions", "loops")

PYTHON_REVEALS = {
    "sequence": "move_forward()\nmove_forward()\nturn_right()\nmove_forward()",
    "conditions": "if has_key:\n    open_door()\nelse:\n    search_for_key()",
    "loops": "for step in range(5):\n    move_forward()",
}
EXPLANATIONS = {
    "sequence": "Sequential execution: instructions run one after another, so their order matters.",
    "conditions": "Conditional logic: an if / else rule picks which action to take depending on a fact.",
    "loops": "Loops: a for loop repeats the same instruction a set number of times.",
}
STATIC_HINTS = {
    "sequence": ["Think about what the guardian must do first.", "Order matters: try walking the path in your head step by step."],
    "conditions": ["What should happen when the key is present? And when it is not?", "Test your rule against both situations."],
    "loops": ["The guardian's memory is small. Is some instruction repeated?", "Use a Repeat for the identical tiles."],
}


def new_learning_progress() -> dict[str, dict[str, Any]]:
    return {c: {"introduced": False, "attempts": 0, "successes": 0, "hints_used": 0,
                "solved": False, "solved_without_hints": False} for c in CONCEPTS}


def introduce(progress: Mapping[str, Any], concept: str) -> dict[str, Any]:
    new = _prepare(progress)
    if concept in CONCEPTS:
        new[concept]["introduced"] = True
    return new


def record_attempt(progress: Mapping[str, Any], concept: str, success: bool,
                   hints_used: int = 0) -> dict[str, Any]:
    """Return NEW progress with one judged attempt recorded."""
    new = _prepare(progress)
    if concept not in CONCEPTS:
        return new
    entry = new[concept]
    entry["introduced"] = True
    entry["attempts"] += 1
    entry["hints_used"] += max(0, int(hints_used))
    if success:
        entry["successes"] += 1
        entry["solved"] = True
        if hints_used <= 0:
            entry["solved_without_hints"] = True
    return new


def _prepare(progress: Mapping[str, Any] | None) -> dict[str, Any]:
    new = copy.deepcopy(dict(progress or {}))
    for concept, entry in new_learning_progress().items():
        new.setdefault(concept, entry)
    return new


def understanding_level(entry: Mapping[str, Any]) -> str:
    if entry.get("solved_without_hints"):
        return "solved_independently"
    if entry.get("solved"):
        return "solved_with_help"
    if entry.get("attempts", 0) > 0:
        return "practicing"
    return "introduced" if entry.get("introduced") else "not_started"


def recommend_next(progress: Mapping[str, Any]) -> str | None:
    """First concept not yet solved, in teaching order; None when all are solved."""
    prog = _prepare(progress)
    for concept in CONCEPTS:
        if not prog[concept]["solved"]:
            return concept
    return None


def reveal_for(progress: Mapping[str, Any], concept: str) -> dict[str, str] | None:
    """The Python reveal, only if the concept was genuinely solved."""
    prog = _prepare(progress)
    if concept in CONCEPTS and prog[concept]["solved"]:
        return {"concept": EXPLANATIONS[concept], "python": PYTHON_REVEALS[concept]}
    return None


def static_hint(concept: str, level: int = 0) -> str:
    hints = STATIC_HINTS.get(concept, ["Take a breath and try the first step again."])
    return hints[max(0, min(level, len(hints) - 1))]


def build_agent(llm):  # pragma: no cover - needs CrewAI; optional (AI-written hints, Phase 4)
    from crewai import Agent
    return Agent(role=ROLE, goal=GOAL, backstory=BACKSTORY, llm=llm,
                 allow_delegation=False, verbose=False)
