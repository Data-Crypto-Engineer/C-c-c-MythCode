"""Pure game logic: build the current scene view and apply a player's choice safely.

Phase 1 uses the prepared (fallback) story in data/quests.json. AI-written scenes arrive in Phase 3-4
and will pass through the same validation.
"""
import copy

from core.quest_manager import GameContent
from core.state_manager import MAX_HISTORY
from core.state_validator import apply_effects
from utils.error_handler import StateValidationError, user_message
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
    return {
        "title": scene["title"],
        "text": scene["text"],
        "location": content.locations[state["world"]["current_location"]]["name"],
        "dialogue": dialogue,
        "choices": [(c["id"], c["label"]) for c in scene.get("choices", [])],
        "is_end": not scene.get("choices"),
    }


def apply_choice(state: dict, choice_id: str, content: GameContent):
    """Return (new_state, message). On any failure the original state is returned unchanged."""
    scene = content.scenes[state["scene_id"]]
    choice = next((c for c in scene.get("choices", []) if c["id"] == choice_id), None)
    if choice is None:
        return state, "That choice isn't available right now."
    try:
        world, notes = apply_effects(
            state["world"], choice.get("effects", {}),
            locations=content.locations, npcs=content.npcs, quests=content.quests,
        )
        if choice["next"] not in content.scenes:
            raise StateValidationError(f"Unknown next scene '{choice['next']}'.")
    except StateValidationError as exc:
        log.warning("Rejected choice %s: %s", choice_id, exc)
        return state, user_message(exc)
    new = copy.deepcopy(state)
    new["world"] = world
    new["scene_id"] = choice["next"]
    new["turn"] += 1
    new["history"] = (new["history"] + [{"turn": new["turn"], "scene": state["scene_id"], "choice": choice_id}])[-MAX_HISTORY:]
    return new, None
