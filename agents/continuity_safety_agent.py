"""AGENT 6: Continuity & Safety.

Python validators are the authority. An optional AI review can only ADD issues
(see merge_reviews); it can never approve something the Python checks rejected.
The keyword list below is a simple first filter, not a complete safety system.
"""
from __future__ import annotations

import re
from typing import Iterable, Mapping

from agents.prompt_utils import plain, render_context
from agents.schemas import ReviewResult, StoryScene
from agents.world_keeper_agent import DEFAULT_RULES, WorldRules, check_world_integrity

ROLE = "Continuity & Safety Reviewer"
GOAL = "Catch contradictions, unsafe content and false progress claims before the player sees them."
BACKSTORY = "A gentle editor for a game that must stay kind, clear and consistent."

MAX_TITLE, MAX_DESCRIPTION, MAX_LINE = 80, 1200, 300
_BLOCKED = re.compile(
    r"\b(gore|gory|dismember\w*|disembowel\w*|torture\w*|sexual\w*|nude|naked|suicide|"
    r"self-harm|kill yourself|rape\w*|slaughter\w*)\b", re.I)
_PROGRESS_CLAIMS = [re.compile(p, re.I) for p in (
    r"\byou(?:'ve| have)? (?:now )?(?:mastered|fully understand)",
    r"\b(?:sequence|conditions?|loops?) (?:is |are )?(?:mastered|complete(?:d)?)\b",
    r"\b(?:unlocked|earned) (?:a |the )?(?:python|code) (?:example|reveal)")]
_CODE = re.compile(r"```|\bdef \w+\(|\bimport \w+|\bfor \w+ in range\(|\b(?:move_forward|turn_right|open_door)\(\)")


def check_scene(scene: StoryScene, world: Mapping, known_characters: Iterable[str] = (),
                rules: WorldRules = DEFAULT_RULES) -> ReviewResult:
    issues: list[str] = []
    if not scene.scene_title or len(scene.scene_title) > MAX_TITLE:
        issues.append(f"scene_title must be 1-{MAX_TITLE} characters")
    if not scene.scene_description or len(scene.scene_description) > MAX_DESCRIPTION:
        issues.append(f"scene_description must be 1-{MAX_DESCRIPTION} characters")
    if any(len(line.text) > MAX_LINE for line in scene.dialogue):
        issues.append(f"each dialogue line must be under {MAX_LINE} characters")
    if len(scene.dialogue) > 6:
        issues.append("use at most 6 dialogue lines")
    if not 2 <= len(scene.actions) <= 5:
        issues.append("offer between 2 and 5 actions")
    ids = [a.id for a in scene.actions]
    if len(ids) != len(set(ids)):
        issues.append("action ids must be unique")
    if any(not a.label or len(a.label) > 100 for a in scene.actions):
        issues.append("each action label must be 1-100 characters")

    text = " ".join([scene.scene_title, scene.scene_description, scene.consequence_preview]
                    + [f"{d.speaker} {d.text}" for d in scene.dialogue]
                    + [a.label for a in scene.actions])
    if _BLOCKED.search(text):
        issues.append("content is not age-appropriate; keep it gentle and non-graphic")
    if any(p.search(text) for p in _PROGRESS_CLAIMS):
        issues.append("do not claim the player mastered or unlocked anything; progress is tracked by the game")
    if _CODE.search(text):
        issues.append("do not include programming code; the game reveals Python itself")

    known = {c.lower() for c in known_characters}
    if known:
        allowed = known | {"narrator", "you"}
        unknown = [c for c in scene.characters if c.lower() not in allowed]
        unknown += [d.speaker for d in scene.dialogue if d.speaker.lower() not in allowed]
        if unknown:
            issues.append("unknown characters: " + ", ".join(sorted(set(unknown))))

    issues += [f"world state problem: {p}" for p in check_world_integrity(world, rules)]
    return ReviewResult(approved=not issues, issues=issues,
                        corrections=[f"Fix: {i}" for i in issues], requires_retry=bool(issues))


def merge_reviews(python_review: ReviewResult, ai_review: ReviewResult | None) -> ReviewResult:
    """Python review is authoritative; the AI review may only add issues."""
    if ai_review is None:
        return python_review
    issues = python_review.issues + [i for i in ai_review.issues if i not in python_review.issues]
    corrections = python_review.corrections + [c for c in ai_review.corrections
                                               if c not in python_review.corrections]
    approved = python_review.approved and ai_review.approved
    return ReviewResult(approved, issues, corrections, requires_retry=not approved)


def build_review_prompt(scene_text: str, context: Mapping) -> tuple[str, str]:
    description = (
        "Review the scene below for a beginner-friendly, age-appropriate fantasy game.\n"
        "Check continuity with the context, kindness, and that no programming code or learning-progress claims appear.\n"
        "World context:\n" + render_context(context) + "\nScene:\n" + plain(scene_text, 3000))
    expected = ("A single JSON object (no markdown) with keys: approved (true or false), issues (list of text), "
                "corrections (list of text), requires_retry (true or false).")
    return description, expected


def build_agent(llm):  # pragma: no cover - optional AI review, not wired by default
    from crewai import Agent
    return Agent(role=ROLE, goal=GOAL, backstory=BACKSTORY, llm=llm,
                 allow_delegation=False, verbose=False)


def build_task(agent, scene_text: str, context: Mapping):  # pragma: no cover
    from crewai import Task
    description, expected = build_review_prompt(scene_text, context)
    return Task(description=description, expected_output=expected, agent=agent)
