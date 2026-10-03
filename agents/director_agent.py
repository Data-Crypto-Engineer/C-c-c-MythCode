"""AGENT 1: Director.

Chooses the next story event. Two modes:
  * rule_based_plan(): deterministic, seeded weighted choice (default, no cost)
  * build_agent()/build_task(): optional AI Director for major quest transitions.
The Director only PROPOSES; the World Keeper validates before anything is saved.
"""
from __future__ import annotations

import random
from typing import Any, Mapping

from agents.player_insight_agent import CONCEPTS
from agents.prompt_utils import render_context
from agents.schemas import DirectorPlan, WorldDelta

ROLE = "Director"
GOAL = "Pick the next story event that fits the world, the player's recent play and the learning path."
BACKSTORY = "A game master who adapts the story but never breaks the rules of the world."

# event id -> (player-facing label, preference that makes it more likely)
# Placeholder ids matching the four pathways in the master prompt. Phase 4 maps
# these to the real quest ids in data/quests.json once I have read that file.
QUEST_EVENTS: dict[str, tuple[str, str]] = {
    "investigate_waterwheel": ("Investigate the broken waterwheel", "building_preference"),
    "negotiate_forest_spirit": ("Negotiate with the forest spirit", "dialogue_preference"),
    "inspect_river_machines": ("Investigate the mechanical creatures by the river", "puzzle_preference"),
    "search_underground_source": ("Search for an underground water source", "exploration_preference"),
}
MASTERY_TARGET = 0.6


def candidate_events(world: Mapping[str, Any], events: Mapping[str, tuple[str, str]] | None = None) -> dict[str, str]:
    events = events or QUEST_EVENTS
    done = set(world.get("completed_quests") or [])
    return {eid: label for eid, (label, _pref) in events.items() if eid not in done}


def next_challenge(player_model: Mapping[str, Any]) -> str:
    mastery = player_model.get("concept_mastery") or {}
    for concept in CONCEPTS:
        if float(mastery.get(concept, 0.0)) < MASTERY_TARGET:
            return concept
    return "none"


def rule_based_plan(action: Mapping[str, Any], world: Mapping[str, Any], player_model: Mapping[str, Any],
                    seed: int = 0, events: Mapping[str, tuple[str, str]] | None = None) -> DirectorPlan:
    """Seeded weighted choice: same inputs + seed give the same plan (testable)."""
    events = events or QUEST_EVENTS
    candidates = candidate_events(world, events)
    challenge = next_challenge(player_model)
    required = ["story_weaver", "continuity_safety"] + (["logic_learning"] if challenge != "none" else [])
    label = str(action.get("label") or "").strip()
    delta = WorldDelta(add_choices=[f"Chose: {label}"[:120]] if label else [])
    if not candidates:
        return DirectorPlan("quest_complete", "Wrap up the village's water crisis.", required,
                            challenge, delta, "All known pathways are completed.")
    ids = sorted(candidates)  # sorted so the seed alone decides the outcome
    weights = [0.25 + float(player_model.get(events[i][1], 0.5)) for i in ids]
    chosen = random.Random(seed).choices(ids, weights=weights, k=1)[0]
    return DirectorPlan(chosen, f"Move the story toward: {candidates[chosen]}.", required, challenge, delta,
                        "Weighted by recent play, bounded by valid events (seeded, not arbitrary).")


def plan_is_valid(plan: DirectorPlan, world: Mapping[str, Any],
                  events: Mapping[str, tuple[str, str]] | None = None) -> bool:
    """An AI plan must choose an event that is actually available."""
    candidates = candidate_events(world, events)
    return plan.next_event in candidates or (not candidates and plan.next_event == "quest_complete")


def build_prompt(context: Mapping[str, Any]) -> tuple[str, str]:
    description = (
        "You are the Director of a gentle, beginner-friendly fantasy adventure. Choose the next story event.\n"
        "Context:\n" + render_context(context) + "\n"
        "Rules: next_event MUST be one of candidate_events. challenge_category must be sequence, conditions, "
        "loops or none. Do not invent places or quests. Propose only small, sensible changes. Keep text short.")
    expected = (
        "A single JSON object (no markdown) with keys: next_event (text, one candidate), "
        "narrative_objective (text), required_agents (list of text), challenge_category (text), "
        "proposed_changes (object with optional keys numeric_deltas, set_values, add_choices, "
        "complete_quests, discover_locations, new_location, add_memories), rationale (short text).")
    return description, expected


def build_agent(llm):  # pragma: no cover - needs CrewAI installed
    from crewai import Agent
    return Agent(role=ROLE, goal=GOAL, backstory=BACKSTORY, llm=llm,
                 allow_delegation=False, verbose=False)


def build_task(agent, context: Mapping[str, Any]):  # pragma: no cover
    from crewai import Task
    description, expected = build_prompt(context)
    return Task(description=description, expected_output=expected, agent=agent)
