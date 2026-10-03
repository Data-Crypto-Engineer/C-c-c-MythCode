"""AGENT 4: World Keeper.

Deterministic Python. It never calls the model. Anything the Director or Story
Weaver *proposes* is checked here and only then applied to a COPY of the world.
If any rule fails, the original world is returned untouched (rollback).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Mapping

from agents.schemas import WorldDelta

ROLE = "World Keeper"
GOAL = "Keep the fantasy world consistent and validate every proposed change."
BACKSTORY = "An archivist of Elarion who records what truly happened and refuses contradictions."


@dataclass(frozen=True)
class WorldRules:
    numeric_bounds: Mapping[str, tuple[int, int]] = field(
        default_factory=lambda: {"village_morale": (0, 100), "forest_spirit_trust": (0, 100)})
    # Ordered states can only move forward (no contradictory un-doing).
    ordered_states: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: {
        "water_supply": ("damaged", "repairing", "flowing"),
        "clockwork_guardian": ("inactive", "awakening", "active")})
    valid_locations: tuple[str, ...] = ()
    valid_quests: tuple[str, ...] = ()
    max_step: int = 25
    max_memories_per_npc: int = 8
    max_choices: int = 200


DEFAULT_RULES = WorldRules()


@dataclass
class TransitionResult:
    ok: bool
    world: dict[str, Any]
    errors: list[str] = field(default_factory=list)


def check_world_integrity(world: Mapping[str, Any], rules: WorldRules = DEFAULT_RULES) -> list[str]:
    """Check a world dict (e.g. loaded from a save file). Returns problems found."""
    problems: list[str] = []
    for key in ("current_location", "discovered_locations", "completed_quests", "important_choices"):
        if key not in world:
            problems.append(f"missing key: {key}")
    for name, (lo, hi) in rules.numeric_bounds.items():
        if name in world:
            value = world[name]
            if not isinstance(value, int) or isinstance(value, bool) or not lo <= value <= hi:
                problems.append(f"{name} must be a whole number from {lo} to {hi}")
    for name, order in rules.ordered_states.items():
        if name in world and world[name] not in order:
            problems.append(f"{name} has unknown value '{world[name]}'")
    discovered = world.get("discovered_locations") or []
    if world.get("current_location") and world["current_location"] not in discovered:
        problems.append("current_location has not been discovered")
    completed = world.get("completed_quests") or []
    if len(completed) != len(set(completed)):
        problems.append("completed_quests contains duplicates")
    return problems


def _valid_locations(world: Mapping[str, Any], rules: WorldRules) -> set[str]:
    return (set(rules.valid_locations) or set(world.get("valid_locations") or [])
            or set(world.get("discovered_locations") or []))


def validate_transition(world: Mapping[str, Any], delta: WorldDelta,
                        rules: WorldRules = DEFAULT_RULES) -> TransitionResult:
    errors: list[str] = []
    new = copy.deepcopy(dict(world))

    for name, change in delta.numeric_deltas.items():
        current = new.get(name)
        if not isinstance(current, int) or isinstance(current, bool):
            errors.append(f"unknown numeric field '{name}'")
            continue
        if abs(change) > rules.max_step:
            errors.append(f"change to '{name}' is too large ({change})")
            continue
        low, high = rules.numeric_bounds.get(name, (0, 100))
        if not low <= current + change <= high:
            errors.append(f"'{name}' would leave its valid range {low}-{high}")
            continue
        new[name] = current + change

    for name, value in delta.set_values.items():
        order = rules.ordered_states.get(name)
        if order is None:
            errors.append(f"unknown state field '{name}'")
        elif value not in order:
            errors.append(f"'{value}' is not a valid value for '{name}'")
        else:
            current = new.get(name)
            if current in order and order.index(value) < order.index(current):
                errors.append(f"'{name}' cannot go backwards from {current} to {value}")
            else:
                new[name] = value

    valid_locations = _valid_locations(world, rules)
    discovered = list(new.get("discovered_locations") or [])
    for location in delta.discover_locations:
        if location not in valid_locations:
            errors.append(f"nonexistent location '{location}'")
        elif location not in discovered:
            discovered.append(location)
    new["discovered_locations"] = discovered
    if delta.new_location is not None:
        if delta.new_location not in valid_locations:
            errors.append(f"nonexistent location '{delta.new_location}'")
        elif delta.new_location not in discovered:
            errors.append(f"location '{delta.new_location}' has not been discovered")
        else:
            new["current_location"] = delta.new_location

    completed = list(new.get("completed_quests") or [])
    valid_quests = set(rules.valid_quests) or set(world.get("valid_quests") or [])
    for quest in delta.complete_quests:
        if quest in completed:
            errors.append(f"quest '{quest}' is already completed")
        elif valid_quests and quest not in valid_quests:
            errors.append(f"unknown quest '{quest}'")
        else:
            completed.append(quest)
    new["completed_quests"] = completed

    choices = list(new.get("important_choices") or [])
    for choice in delta.add_choices:
        choice = choice.strip()
        if not choice or len(choice) > 120:
            errors.append("a recorded choice is empty or longer than 120 characters")
        else:
            choices.append(choice)
    if len(choices) > rules.max_choices:
        errors.append("too many recorded choices")
    new["important_choices"] = choices  # append-only: earlier choices are never removed

    npcs = set(new.get("npcs") or [])
    memories = {k: list(v) for k, v in (new.get("character_memories") or {}).items()}
    for npc, items in delta.add_memories.items():
        if npcs and npc not in npcs:
            errors.append(f"memory for unknown character '{npc}'")
            continue
        for text in items:
            text = text.strip()
            if not text or len(text) > 200:
                errors.append(f"a memory for '{npc}' is empty or longer than 200 characters")
            else:
                memories.setdefault(npc, []).append(text)
        if npc in memories:
            memories[npc] = memories[npc][-rules.max_memories_per_npc:]  # oldest dropped
    new["character_memories"] = memories

    if errors:
        return TransitionResult(False, copy.deepcopy(dict(world)), errors)
    return TransitionResult(True, new, [])


def memories_for(world: Mapping[str, Any], npc: str, limit: int = 2) -> list[str]:
    return list((world.get("character_memories") or {}).get(npc, []))[-limit:]


def build_world_context(world: Mapping[str, Any], present_npcs: tuple[str, ...] | list[str] = (),
                        memory_limit: int = 2) -> dict[str, Any]:
    """Compact, prompt-sized view of the world (never the full history)."""
    return {
        "kingdom": world.get("kingdom"),
        "current_location": world.get("current_location"),
        "water_supply": world.get("water_supply"),
        "clockwork_guardian": world.get("clockwork_guardian"),
        "village_morale": world.get("village_morale"),
        "forest_spirit_trust": world.get("forest_spirit_trust"),
        "completed_quests": list(world.get("completed_quests") or []),
        "recent_choices": list(world.get("important_choices") or [])[-5:],
        "character_memories": {n: memories_for(world, n, memory_limit) for n in present_npcs
                               if memories_for(world, n, memory_limit)},
    }


def build_agent(llm):  # pragma: no cover - needs CrewAI installed
    from crewai import Agent
    return Agent(role=ROLE, goal=GOAL, backstory=BACKSTORY, llm=llm,
                 allow_delegation=False, verbose=False)
