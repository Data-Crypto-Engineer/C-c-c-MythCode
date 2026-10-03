"""AGENT 2: Player Insight.

Deterministic Python (no model call). Keeps an evolving, evidence-based model of
what the player has DONE: never a personality type, never sensitive traits.
All starting values are neutral placeholders, not observed data.

Safeguards: each action moves a preference by at most PREFERENCE_STEP (0.08),
unused preferences drift back toward neutral (so adaptations are reversible),
and challenge level changes only after a window of 5 puzzle results.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping

ROLE = "Player Insight Analyst"
GOAL = "Describe what the player has actually done, with humility about small samples."
BACKSTORY = "A careful observer who only trusts repeated evidence."

CONCEPTS = ("sequence", "conditions", "loops")
PREFERENCE_KEYS = ("exploration_preference", "dialogue_preference", "puzzle_preference",
                   "building_preference", "experimentation_preference")
EVENT_TO_PREFERENCE = {
    "explore": "exploration_preference", "dialogue": "dialogue_preference",
    "puzzle": "puzzle_preference", "build": "building_preference",
    "experiment": "experimentation_preference"}
NEUTRAL = 0.5
PREFERENCE_STEP = 0.08
DECAY_STEP = 0.01


def default_player_model() -> dict[str, Any]:
    model: dict[str, Any] = {key: NEUTRAL for key in PREFERENCE_KEYS}
    model.update({
        "hint_usage": 0.0,
        "challenge_level": 1,
        "concept_mastery": {c: 0.0 for c in CONCEPTS},
        "recent_puzzle_results": [],
        "events_observed": 0,
        "confidence": 0.0,
    })
    return model


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, round(value, 4)))


def observe(model: Mapping[str, Any] | None, event: Mapping[str, Any]) -> dict[str, Any]:
    """Return a NEW model updated from one observed event.

    event = {"kind": explore|dialogue|puzzle|build|experiment,
             "success": bool, "hints_used": int, "concept": sequence|conditions|loops}
    Unknown kinds leave the model unchanged.
    """
    new = copy.deepcopy(dict(model or {}))
    for key, value in default_player_model().items():
        new.setdefault(key, copy.deepcopy(value))
    kind = event.get("kind")
    target = EVENT_TO_PREFERENCE.get(kind)
    if target is None:
        return new

    new["events_observed"] = int(new["events_observed"]) + 1
    for key in PREFERENCE_KEYS:
        current = float(new[key])
        if key == target:
            current += PREFERENCE_STEP * (1.0 - current)
        else:
            current += DECAY_STEP * (NEUTRAL - current)
        new[key] = _clamp(current)

    if kind == "puzzle":
        success = bool(event.get("success"))
        hints = max(0, int(event.get("hints_used") or 0))
        used_hint = 1.0 if hints > 0 else 0.0
        new["hint_usage"] = _clamp(float(new["hint_usage"]) + 0.1 * (used_hint - float(new["hint_usage"])))
        concept = event.get("concept")
        if concept in CONCEPTS:
            mastery = float(new["concept_mastery"].get(concept, 0.0))
            if success:
                mastery += 0.2 if hints == 0 else 0.1
            else:
                mastery -= 0.05
            new["concept_mastery"][concept] = _clamp(mastery)
        window = (list(new["recent_puzzle_results"]) + [1 if (success and hints == 0) else 0])[-5:]
        level = int(new["challenge_level"])
        if len(window) == 5:
            if sum(window) >= 4 and level < 5:
                level, window = level + 1, []
            elif sum(window) <= 1 and level > 1:
                level, window = level - 1, []
        new["challenge_level"] = level
        new["recent_puzzle_results"] = window

    new["confidence"] = min(1.0, new["events_observed"] / 20)
    return new


def describe(model: Mapping[str, Any]) -> str:
    """One short, non-judgemental sentence for prompts."""
    labels = {"exploration_preference": "exploring", "dialogue_preference": "talking with characters",
              "puzzle_preference": "puzzles", "building_preference": "building",
              "experimentation_preference": "experimenting"}
    best = max(PREFERENCE_KEYS, key=lambda k: float(model.get(k, NEUTRAL)))
    lean = (f"has recently leaned toward {labels[best]}" if float(model.get(best, NEUTRAL)) >= 0.55
            else "shows no clear preference yet")
    hints = float(model.get("hint_usage", 0.0))
    hint_text = "rarely uses hints" if hints < 0.2 else "sometimes uses hints" if hints < 0.5 else "often uses hints"
    return (f"The player {lean}, {hint_text}; challenge level {model.get('challenge_level', 1)}; "
            f"confidence in this picture {float(model.get('confidence', 0.0)):.2f} (low means few observations).")


def build_agent(llm):  # pragma: no cover - needs CrewAI; not used by the default workflow
    from crewai import Agent
    return Agent(role=ROLE, goal=GOAL, backstory=BACKSTORY, llm=llm,
                 allow_delegation=False, verbose=False)
