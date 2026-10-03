"""Orchestration: the one function the app calls is process_player_action().

Workflow (conditional, not every agent every time):
  action -> Player Insight (Python) -> Director (Python by default; AI only for
  major quest transitions) -> Story Weaver (AI, with retries and fallback)
  -> Continuity & Safety (Python) -> World Keeper validation (Python) -> result.

Cost design: at most ONE CrewAI kickoff per player action (1 model call for a
normal action, 2 for a major quest transition). The other agents run as plain
Python. NOTE: CrewAI Flows are not used in Phase 3 (their API was not verified);
this is ordinary Python control flow around a Crew.

This module does NOT save anything. The caller persists result.world only.
"""
from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from agents import (continuity_safety_agent as safety, director_agent, player_insight_agent as insight,
                    story_weaver_agent as weaver, world_keeper_agent as keeper)
from agents.prompt_utils import plain
from agents.schemas import (DirectorPlan, ReviewResult, StoryScene, WorldDelta, parse_director_plan,
                            parse_story_scene)
from utils.ai_errors import (AIResponseError, ErrorKind, call_with_retries, classify_exception,
                             log_error, user_message)
from utils.llm_config import LLMSettings

MAJOR_ACTION_TYPES = frozenset({"quest_transition"})
MAX_STORY_RETRIES = 1  # bounded regeneration after a failed safety/format check
ACTION_TO_EVENT = {"explore": "explore", "dialogue": "dialogue", "puzzle": "puzzle",
                   "build": "build", "experiment": "experiment"}


@dataclass
class CrewRequest:
    director_context: dict[str, Any] | None
    story_context: dict[str, Any]
    corrections: list[str] = field(default_factory=list)


CrewRunner = Callable[[LLMSettings, CrewRequest], dict[str, str | None]]


@dataclass
class ActionResult:
    scene: StoryScene
    world: dict[str, Any]
    player_model: dict[str, Any]
    plan: DirectorPlan
    review: ReviewResult
    used_fallback: bool
    notices: list[str] = field(default_factory=list)      # safe to show the player
    world_errors: list[str] = field(default_factory=list)  # technical, for logs/debug
    llm_runs: int = 0                                       # successful crew runs this action


def _task_text(task) -> str | None:  # pragma: no cover - needs CrewAI output objects
    output = getattr(task, "output", None)
    if output is None:
        return None
    raw = getattr(output, "raw", None)
    return raw if raw is not None else str(output)


def default_crew_runner(settings: LLMSettings, request: CrewRequest) -> dict[str, str | None]:  # pragma: no cover
    """Real CrewAI run. Needs CrewAI installed; not executed in this build's tests."""
    from crewai import Crew, Process
    from agents.llm_factory import build_llm

    llm = build_llm(settings)
    agents, tasks, director_task = [], [], None
    if request.director_context is not None:
        director = director_agent.build_agent(llm)
        director_task = director_agent.build_task(director, request.director_context)
        agents.append(director)
        tasks.append(director_task)
    writer = weaver.build_agent(llm)
    story_task = weaver.build_task(writer, request.story_context, request.corrections,
                                   context_tasks=[director_task] if director_task else None)
    agents.append(writer)
    tasks.append(story_task)
    Crew(agents=agents, tasks=tasks, process=Process.sequential, verbose=False).kickoff()
    return {"director": _task_text(director_task) if director_task else None,
            "story": _task_text(story_task)}


def _story_context(world, model, action, history, plan, npcs) -> dict[str, Any]:
    return {
        "location": world.get("current_location"),
        "world": keeper.build_world_context(world, npcs),
        "player_action": plain(action.get("label") or action.get("id") or "continue", 120),
        "player_summary": insight.describe(model),
        "recent_history": [plain(h, 160) for h in list(history)[-5:]],
        "allowed_characters": list(npcs),
        "plan": {"event": plan.next_event, "objective": plan.narrative_objective,
                 "challenge": plan.challenge_category},
    }


def process_player_action(
    action: Mapping[str, Any], world: Mapping[str, Any], player_model: Mapping[str, Any] | None,
    history: Sequence[str] = (), *, settings: LLMSettings | None = None, runner: CrewRunner | None = None,
    seed: int = 0, known_characters: Sequence[str] | None = None,
    rules: keeper.WorldRules = keeper.DEFAULT_RULES, sleep: Callable[[float], None] = time.sleep,
) -> ActionResult:
    """Run one player action. Never raises for AI problems; falls back instead.

    action: {"type": explore|dialogue|puzzle|build|experiment|quest_transition,
             "id": str, "label": str, "success": bool, "hints_used": int, "concept": str}
    """
    notices: list[str] = []
    runs = 0
    npcs = list(known_characters if known_characters is not None else (world.get("npcs") or []))

    # 1. Player Insight (Python): evidence from what the player actually did.
    kind = ACTION_TO_EVENT.get(str(action.get("type")))
    model = insight.observe(player_model, {**action, "kind": kind}) if kind else insight.observe(player_model, {})

    # 2. Director (Python by default).
    plan = director_agent.rule_based_plan(action, world, model, seed)
    is_major = action.get("type") in MAJOR_ACTION_TYPES
    scene: StoryScene | None = None
    review = ReviewResult()
    used_fallback = False

    if settings is None:
        notices.append(user_message(ErrorKind.CONFIG))
        used_fallback = True
    else:
        runner = runner or default_crew_runner
        director_ctx = None
        if is_major:
            director_ctx = {
                "player_action": plain(action.get("label") or "", 120),
                "candidate_events": director_agent.candidate_events(world),
                "world": keeper.build_world_context(world, npcs),
                "player_summary": insight.describe(model),
                "recommended_challenge": director_agent.next_challenge(model)}
        corrections: list[str] = []
        for attempt in range(MAX_STORY_RETRIES + 1):
            request = CrewRequest(director_ctx if attempt == 0 else None,
                                  _story_context(world, model, action, history, plan, npcs), corrections)
            try:
                raw = call_with_retries(lambda: runner(settings, request), settings.max_retries,
                                        sleep=sleep, secrets=(settings.api_key,))
                runs += 1
            except Exception as exc:  # noqa: BLE001 - classified; never crashes the game
                notices.append(user_message(log_error(exc, "crew run", (settings.api_key,))))
                break
            if attempt == 0 and raw.get("director"):
                try:
                    ai_plan = parse_director_plan(raw["director"])
                    if director_agent.plan_is_valid(ai_plan, world):
                        plan = ai_plan
                except AIResponseError as exc:
                    log_error(exc, "director output", (settings.api_key,))
            try:
                candidate = parse_story_scene(raw.get("story"))
            except AIResponseError as exc:
                log_error(exc, "story output", (settings.api_key,))
                corrections = ["Return one valid JSON object exactly as specified, with 2-4 actions."]
                continue
            review = safety.check_scene(candidate, world, npcs, rules)
            if review.approved:
                scene = candidate
                break
            corrections = review.corrections
        if scene is None:
            used_fallback = True
            if not notices:
                notices.append(user_message(ErrorKind.BAD_RESPONSE))

    if scene is None:
        scene = weaver.fallback_scene(world.get("current_location"), npcs)
        review = ReviewResult(approved=True)

    # 3. World Keeper (Python): validate before anything is applied.
    if used_fallback:
        new_world, world_errors = copy.deepcopy(dict(world)), []
    else:
        outcome = keeper.validate_transition(world, plan.proposed_changes, rules)
        new_world, world_errors = outcome.world, outcome.errors
        if not outcome.ok:
            plan = DirectorPlan(plan.next_event, plan.narrative_objective, plan.required_agents,
                                plan.challenge_category, WorldDelta(), plan.rationale)
    return ActionResult(scene, new_world, model, plan, review, used_fallback, notices, world_errors, runs)
