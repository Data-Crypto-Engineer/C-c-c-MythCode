"""AGENT 3: Story Weaver. Writes the next scene as structured JSON.

Includes a predefined fallback scene so the game stays playable if the AI fails.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from agents.prompt_utils import plain, render_context
from agents.schemas import DialogueLine, SceneAction, StoryScene

ROLE = "Story Weaver"
GOAL = "Write the next scene so it reflects the player's choices and the world's memory."
BACKSTORY = "A warm storyteller of Elarion who never forgets what the player did."


def build_prompt(context: Mapping[str, Any], corrections: Sequence[str] = (),
                 has_director_task: bool = False) -> tuple[str, str]:
    parts = [
        "Write ONE scene for a gentle, age-appropriate, beginner-friendly fantasy adventure.",
        "Context:\n" + render_context(context),
        "Rules:",
        "- Use only the characters listed in allowed_characters (plus Narrator).",
        "- Reflect character_memories and recent_choices where relevant; do not ignore past choices.",
        "- Do NOT include programming code and do NOT say the player has learned or mastered anything.",
        "- Do not reveal every future consequence; hint at most one.",
        "- Offer 2 to 4 actions. Each has a short snake_case id and a clear label.",
        "- Keep scene_description under 900 characters and each dialogue line under 250.",
    ]
    if has_director_task:
        parts.insert(2, "Follow the Director's plan from the previous task.")
    if corrections:
        parts.append("Your previous attempt had problems. Fix them:\n" + "\n".join(f"- {plain(c, 200)}" for c in corrections))
    expected = (
        "A single JSON object (no markdown) with keys: scene_title (text), scene_description (text), "
        "dialogue (list of objects with speaker and text), actions (list of objects with id and label), "
        "consequence_preview (text, may be empty), characters (list of names), event_category (text).")
    return "\n".join(parts), expected


def fallback_scene(location: str | None, characters: Sequence[str] = ()) -> StoryScene:
    """Predefined safe scene. Action ids are generic; Phase 4 maps them to real game actions."""
    place = plain(location or "the village", 60)
    speaker = characters[0] if characters else "Narrator"
    return StoryScene(
        scene_title=f"A Quiet Moment in {place}",
        scene_description=(f"The air in {place} is calm. Somewhere nearby the village's water problem still waits "
                           "to be solved, and the path ahead is yours to choose."),
        dialogue=[DialogueLine(speaker, "Take your time. Look around, talk to someone, and decide what feels right.")],
        actions=[SceneAction("look_around", "Look around carefully"),
                 SceneAction("talk_nearby", "Talk to someone nearby"),
                 SceneAction("continue_quest", "Continue with the water crisis")],
        consequence_preview="",
        characters=[speaker] if characters else [],
        event_category="fallback")


def build_agent(llm):  # pragma: no cover - needs CrewAI installed
    from crewai import Agent
    return Agent(role=ROLE, goal=GOAL, backstory=BACKSTORY, llm=llm,
                 allow_delegation=False, verbose=False)


def build_task(agent, context: Mapping[str, Any], corrections: Sequence[str] = (), context_tasks=None):  # pragma: no cover
    from crewai import Task
    description, expected = build_prompt(context, corrections, has_director_task=bool(context_tasks))
    kwargs = {"context": list(context_tasks)} if context_tasks else {}
    return Task(description=description, expected_output=expected, agent=agent, **kwargs)
