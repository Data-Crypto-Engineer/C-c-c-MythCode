"""Deterministic validation of every world change. The app, not the AI, has the final say.

apply_effects() works on a copy: if anything is invalid it raises StateValidationError
and the caller keeps the original state (rollback).
"""
import copy
from typing import Iterable, Tuple

from models.world import BOUNDED_FIELDS, GUARDIAN_STATES, WATER_STATES
from utils.error_handler import StateValidationError

ALLOWED_EFFECT_KEYS = {"set", "add", "move_to", "discover", "complete_quest", "record_choice", "remember"}
REQUIRED_WORLD_KEYS = (
    "kingdom", "current_location", "water_supply", "forest_spirit_trust", "clockwork_guardian",
    "village_morale", "active_quest", "completed_quests", "discovered_locations",
    "important_choices", "character_memories",
)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_world_state(world: dict, locations: Iterable[str], quests: Iterable[str]) -> list:
    """Return a list of problems with a whole world (used for saved files). Empty = valid."""
    locations, quests, issues = set(locations), set(quests), []
    if not isinstance(world, dict):
        return ["World state is not an object."]
    for key in REQUIRED_WORLD_KEYS:
        if key not in world:
            issues.append(f"Missing world field '{key}'.")
    if issues:
        return issues
    if world["water_supply"] not in WATER_STATES:
        issues.append("Invalid water_supply value.")
    if world["clockwork_guardian"] not in GUARDIAN_STATES:
        issues.append("Invalid clockwork_guardian value.")
    for field, (lo, hi) in BOUNDED_FIELDS.items():
        if not _is_int(world[field]) or not lo <= world[field] <= hi:
            issues.append(f"{field} must be a whole number from {lo} to {hi}.")
    if not isinstance(world["discovered_locations"], list) or any(l not in locations for l in world["discovered_locations"]):
        issues.append("Unknown location in discovered_locations.")
    elif len(set(world["discovered_locations"])) != len(world["discovered_locations"]):
        issues.append("Duplicate discovered location.")
    elif world["current_location"] not in world["discovered_locations"]:
        issues.append("Current location has not been discovered.")
    if not isinstance(world["completed_quests"], list) or any(q not in quests for q in world["completed_quests"]):
        issues.append("Unknown quest in completed_quests.")
    elif len(set(world["completed_quests"])) != len(world["completed_quests"]):
        issues.append("Duplicate completed quest.")
    if world["active_quest"] not in quests:
        issues.append("Unknown active_quest.")
    if not isinstance(world["important_choices"], list) or not all(
        isinstance(c, dict) and isinstance(c.get("id"), str) and isinstance(c.get("text"), str)
        for c in world["important_choices"]
    ):
        issues.append("Malformed important_choices.")
    mem = world["character_memories"]
    if not isinstance(mem, dict) or not all(
        isinstance(v, dict) and all(isinstance(t, str) and isinstance(x, str) for t, x in v.items())
        for v in mem.values()
    ):
        issues.append("Malformed character_memories.")
    return issues


def apply_effects(world: dict, effects: dict, *, locations: Iterable[str], npcs: Iterable[str],
                  quests: Iterable[str]) -> Tuple[dict, list]:
    """Validate a proposed change and return (new_world, notes). Raises StateValidationError."""
    locations, npcs, quests = set(locations), set(npcs), set(quests)
    issues, notes = [], []
    new = copy.deepcopy(world)

    if not isinstance(effects, dict):
        raise StateValidationError("Effects must be an object.")
    unknown = set(effects) - ALLOWED_EFFECT_KEYS
    if unknown:
        issues.append(f"Unknown effect(s): {', '.join(sorted(unknown))}.")

    for loc in effects.get("discover", []):
        if loc not in locations:
            issues.append(f"Cannot discover nonexistent location '{loc}'.")
        elif loc not in new["discovered_locations"]:
            new["discovered_locations"].append(loc)

    for key, value in effects.get("set", {}).items():
        if key == "water_supply":
            if value not in WATER_STATES:
                issues.append(f"Invalid water_supply '{value}'.")
            elif WATER_STATES.index(value) < WATER_STATES.index(new["water_supply"]):
                issues.append("Water supply cannot get worse through this action.")
            else:
                new["water_supply"] = value
        elif key == "clockwork_guardian":
            if value not in GUARDIAN_STATES:
                issues.append(f"Invalid clockwork_guardian '{value}'.")
            else:
                new["clockwork_guardian"] = value
        else:
            issues.append(f"Field '{key}' cannot be set directly.")

    for key, delta in effects.get("add", {}).items():
        if key not in BOUNDED_FIELDS:
            issues.append(f"Field '{key}' cannot be changed by addition.")
        elif not _is_int(delta):
            issues.append(f"Change for '{key}' must be a whole number.")
        else:
            lo, hi = BOUNDED_FIELDS[key]
            wanted = new[key] + delta
            new[key] = max(lo, min(hi, wanted))
            if new[key] != wanted:
                notes.append(f"{key} limited to {new[key]}.")

    target = effects.get("move_to")
    if target is not None:
        if target not in locations:
            issues.append(f"Cannot move to nonexistent location '{target}'.")
        elif target not in new["discovered_locations"]:
            issues.append(f"Location '{target}' has not been discovered yet.")
        else:
            new["current_location"] = target

    quest_id = effects.get("complete_quest")
    if quest_id is not None:
        if quest_id not in quests:
            issues.append(f"Unknown quest '{quest_id}'.")
        elif quest_id in new["completed_quests"]:
            issues.append(f"Quest '{quest_id}' is already completed.")
        else:
            new["completed_quests"].append(quest_id)

    choice = effects.get("record_choice")
    if choice is not None:
        if not (isinstance(choice, dict) and isinstance(choice.get("id"), str) and choice["id"].strip()
                and isinstance(choice.get("text"), str) and choice["text"].strip()):
            issues.append("record_choice needs non-empty 'id' and 'text'.")
        else:
            new["important_choices"].append({"id": choice["id"], "text": choice["text"]})

    for npc, tags in effects.get("remember", {}).items():
        if npc not in npcs:
            issues.append(f"Unknown character '{npc}'.")
            continue
        if not isinstance(tags, dict):
            issues.append(f"Memories for '{npc}' must be an object.")
            continue
        slot = new["character_memories"].setdefault(npc, {})
        for tag, text in tags.items():
            if not (isinstance(tag, str) and tag and isinstance(text, str) and text):
                issues.append("Memory tag and text must be non-empty strings.")
            elif tag in slot and slot[tag] != text:
                issues.append(f"Memory '{tag}' for '{npc}' would contradict an earlier memory.")
            else:
                slot[tag] = text

    if issues:
        raise StateValidationError(issues)
    final = validate_world_state(new, locations, quests)
    if final:
        raise StateValidationError(final)
    # Important decisions are append-only: nothing earlier may disappear.
    if new["important_choices"][: len(world["important_choices"])] != world["important_choices"]:
        raise StateValidationError("Earlier decisions may not be changed.")
    return new, notes
