"""Pure game logic: build the current scene view and apply a player's actions safely.

Phase 1-2 use the prepared (fallback) story in data/quests.json. AI-written scenes arrive in
Phase 3-4 and will pass through the same validation.

Every function that changes the game returns a NEW state and leaves the old one untouched, so a
failed action can never damage saved progress.
"""
import copy

from core.learning_engine import (
    evaluate_puzzle, mark_introduced, record_attempt, record_hint,
)
from core.quest_manager import GameContent
from core.state_manager import MAX_HISTORY
from core.state_validator import apply_effects
from models.learning import CONCEPT_LABELS
from utils.error_handler import PuzzleInputError, StateValidationError, user_message
from utils.logger import get_logger

log = get_logger()


def get_scene_view(state: dict, content: GameContent) -> dict:
    scene = content.scenes[state["scene_id"]]
    memories = state["world"]["character_memories"]
    dialogue = []
    for entry in scene.get("dialogue", []):
        npc_id = entry["npc"]
        line, matched = entry["line"], False
        for alt in entry.get("alts", []):
            if alt["needs_memory"] in memories.get(npc_id, {}):
                line, matched = alt["line"], True
                break
        if entry.get("only_if_alt") and not matched:
            continue
        dialogue.append((content.npcs[npc_id].name, line))

    concepts = state["learning"]["concepts"]
    puzzle_view = None
    puzzle_id = scene.get("puzzle")
    if puzzle_id:
        puzzle = content.puzzles[puzzle_id]
        used = concepts[puzzle["concept"]]["hints_used"]
        puzzle_view = {
            "id": puzzle_id, "concept": puzzle["concept"], "kind": puzzle["kind"],
            "title": puzzle["title"], "instructions": puzzle["instructions"], "config": puzzle["config"],
            "hints_shown": puzzle["hints"][:used], "hints_total": len(puzzle["hints"]),
        }

    reveal_view = None
    reveal_concept = scene.get("reveal")
    if reveal_concept and concepts[reveal_concept]["python_unlocked"]:
        reveal_view = reveal_for(reveal_concept, content)

    return {
        "title": scene["title"],
        "text": scene["text"],
        "location": content.locations[state["world"]["current_location"]]["name"],
        "dialogue": dialogue,
        "choices": [(c["id"], c["label"]) for c in scene.get("choices", [])],
        "puzzle": puzzle_view,
        "reveal": reveal_view,
        "is_end": not scene.get("choices") and not puzzle_id,
    }


def reveal_for(concept: str, content: GameContent):
    """The Python reveal for a concept (callers must check it is unlocked first)."""
    for puzzle in content.puzzles.values():
        if puzzle["concept"] == concept:
            r = puzzle["reveal"]
            return {"concept": CONCEPT_LABELS[concept], "name": r["name"], "python": r["python"],
                    "explanation": r["explanation"]}
    return None


def _enter_scene(new_state: dict, content: GameContent) -> None:
    """Called after moving to a scene: a puzzle scene counts as 'concept encountered'."""
    puzzle_id = content.scenes[new_state["scene_id"]].get("puzzle")
    if puzzle_id:
        concept = content.puzzles[puzzle_id]["concept"]
        new_state["learning"] = mark_introduced(new_state["learning"], concept)


def _advance(state: dict, effects: dict, next_scene: str, history_choice: str, content: GameContent) -> dict:
    """Validate effects, then return the new state. Raises StateValidationError (caller keeps old state)."""
    world, _notes = apply_effects(
        state["world"], effects, locations=content.locations, npcs=content.npcs, quests=content.quests,
    )
    if next_scene not in content.scenes:
        raise StateValidationError(f"Unknown next scene '{next_scene}'.")
    new = copy.deepcopy(state)
    new["world"] = world
    new["scene_id"] = next_scene
    new["turn"] += 1
    new["history"] = (new["history"] + [{"turn": new["turn"], "scene": state["scene_id"], "choice": history_choice}])[-MAX_HISTORY:]
    _enter_scene(new, content)
    return new


def apply_choice(state: dict, choice_id: str, content: GameContent):
    """Return (new_state, message). On any failure the original state is returned unchanged."""
    scene = content.scenes[state["scene_id"]]
    choice = next((c for c in scene.get("choices", []) if c["id"] == choice_id), None)
    if choice is None:
        return state, "That choice isn't available right now."
    try:
        return _advance(state, choice.get("effects", {}), choice["next"], choice_id, content), None
    except StateValidationError as exc:
        log.warning("Rejected choice %s: %s", choice_id, exc)
        return state, user_message(exc)


def _current_puzzle(state: dict, content: GameContent):
    scene = content.scenes[state["scene_id"]]
    puzzle_id = scene.get("puzzle")
    return (scene, puzzle_id, content.puzzles[puzzle_id]) if puzzle_id else (scene, None, None)


def submit_puzzle(state: dict, submission, content: GameContent):
    """Judge a puzzle submission deterministically and update progress.

    Returns (new_state, result). result keys: valid, solved, feedback, trace.
      * malformed submission  -> original state, valid=False (not counted as an attempt)
      * valid but wrong       -> attempt recorded, player stays in the scene
      * solved                -> attempt recorded, scene effects validated and applied, scene advances
    If the solve's world effects fail validation, the original state is returned unchanged.
    """
    scene, puzzle_id, puzzle = _current_puzzle(state, content)
    if puzzle is None:
        return state, {"valid": False, "solved": False, "feedback": "There is no challenge here.", "trace": None}
    try:
        outcome = evaluate_puzzle(puzzle, submission)
    except PuzzleInputError as exc:
        return state, {"valid": False, "solved": False, "feedback": user_message(exc), "trace": None}

    result = {"valid": True, "solved": outcome["solved"], "feedback": outcome["feedback"], "trace": outcome["trace"]}
    new = copy.deepcopy(state)
    new["learning"] = record_attempt(new["learning"], puzzle["concept"], outcome["solved"])
    if not outcome["solved"]:
        return new, result
    solve = scene["on_solve"]
    try:
        advanced = _advance(new, solve.get("effects", {}), solve["next"], f"solved:{puzzle_id}", content)
    except StateValidationError as exc:
        log.warning("Rejected puzzle solve %s: %s", puzzle_id, exc)
        result.update(solved=False, feedback=user_message(exc))
        return state, result
    return advanced, result


def request_hint(state: dict, content: GameContent):
    """Reveal the next hint for the current puzzle. Returns (new_state, hint_text or None if none left)."""
    _scene, _pid, puzzle = _current_puzzle(state, content)
    if puzzle is None:
        return state, None
    used = state["learning"]["concepts"][puzzle["concept"]]["hints_used"]
    if used >= len(puzzle["hints"]):
        return state, None
    new = copy.deepcopy(state)
    new["learning"] = record_hint(new["learning"], puzzle["concept"])
    return new, puzzle["hints"][used]
