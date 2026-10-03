"""Structured outputs shared by the agents (plain dataclasses, no extra dependency).

AI text is turned into these objects only through the parse_* functions, which
raise AIResponseError for empty, malformed or wrongly shaped output.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from utils.ai_errors import AIResponseError

CHALLENGE_CATEGORIES = ("sequence", "conditions", "loops", "none")


@dataclass
class WorldDelta:
    """A *proposed* change to the world. Nothing here is applied until validated."""
    numeric_deltas: dict[str, int] = field(default_factory=dict)
    set_values: dict[str, str] = field(default_factory=dict)
    add_choices: list[str] = field(default_factory=list)
    complete_quests: list[str] = field(default_factory=list)
    discover_locations: list[str] = field(default_factory=list)
    new_location: str | None = None
    add_memories: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class DirectorPlan:
    next_event: str
    narrative_objective: str
    required_agents: list[str] = field(default_factory=list)
    challenge_category: str = "none"
    proposed_changes: WorldDelta = field(default_factory=WorldDelta)
    rationale: str = ""


@dataclass
class DialogueLine:
    speaker: str
    text: str


@dataclass
class SceneAction:
    id: str
    label: str


@dataclass
class StoryScene:
    scene_title: str
    scene_description: str
    dialogue: list[DialogueLine] = field(default_factory=list)
    actions: list[SceneAction] = field(default_factory=list)
    consequence_preview: str = ""
    characters: list[str] = field(default_factory=list)
    event_category: str = "story"


@dataclass
class ReviewResult:
    approved: bool = True
    issues: list[str] = field(default_factory=list)
    corrections: list[str] = field(default_factory=list)
    requires_retry: bool = False


# ---------------------------------------------------------------- JSON helpers
def extract_json_text(raw: Any) -> str:
    if raw is None or not str(raw).strip():
        raise AIResponseError("empty model response")
    text = str(raw).strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S | re.I)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise AIResponseError("no JSON object found in model response")
    return text[start:end + 1]


def load_json_object(raw: Any) -> dict[str, Any]:
    try:
        data = json.loads(extract_json_text(raw))
    except json.JSONDecodeError as exc:
        raise AIResponseError("malformed JSON in model response") from exc
    if not isinstance(data, dict):
        raise AIResponseError("model response is not a JSON object")
    return data


def _text(value: Any, name: str, required: bool = True, max_len: int = 2000) -> str:
    if value is None or value == "":
        if required:
            raise AIResponseError(f"missing field: {name}")
        return ""
    if not isinstance(value, str):
        raise AIResponseError(f"field {name} must be text")
    return value.strip()[:max_len]


def _str_list(value: Any, name: str) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise AIResponseError(f"field {name} must be a list of text")
    return [v.strip() for v in value if v.strip()]


# --------------------------------------------------------------------- parsers
def parse_world_delta(data: Any) -> WorldDelta:
    if data in (None, ""):
        return WorldDelta()
    if not isinstance(data, Mapping):
        raise AIResponseError("proposed_changes must be an object")
    numeric = data.get("numeric_deltas") or {}
    values = data.get("set_values") or {}
    memories = data.get("add_memories") or {}
    if not isinstance(numeric, Mapping) or not all(
            isinstance(v, int) and not isinstance(v, bool) for v in numeric.values()):
        raise AIResponseError("numeric_deltas must map names to whole numbers")
    if not isinstance(values, Mapping) or not all(isinstance(v, str) for v in values.values()):
        raise AIResponseError("set_values must map names to text")
    if not isinstance(memories, Mapping):
        raise AIResponseError("add_memories must be an object")
    new_location = data.get("new_location")
    if new_location is not None and not isinstance(new_location, str):
        raise AIResponseError("new_location must be text")
    return WorldDelta(
        numeric_deltas={str(k): int(v) for k, v in numeric.items()},
        set_values={str(k): v for k, v in values.items()},
        add_choices=_str_list(data.get("add_choices"), "add_choices"),
        complete_quests=_str_list(data.get("complete_quests"), "complete_quests"),
        discover_locations=_str_list(data.get("discover_locations"), "discover_locations"),
        new_location=(new_location or None),
        add_memories={str(k): _str_list(v, "add_memories") for k, v in memories.items()},
    )


def parse_director_plan(raw: Any) -> DirectorPlan:
    data = load_json_object(raw)
    category = _text(data.get("challenge_category") or "none", "challenge_category").lower()
    if category not in CHALLENGE_CATEGORIES:
        raise AIResponseError("unknown challenge_category")
    return DirectorPlan(
        next_event=_text(data.get("next_event"), "next_event", max_len=80),
        narrative_objective=_text(data.get("narrative_objective"), "narrative_objective", max_len=300),
        required_agents=_str_list(data.get("required_agents"), "required_agents"),
        challenge_category=category,
        proposed_changes=parse_world_delta(data.get("proposed_changes")),
        rationale=_text(data.get("rationale"), "rationale", required=False, max_len=400),
    )


def parse_story_scene(raw: Any) -> StoryScene:
    data = load_json_object(raw)
    dialogue = []
    for item in data.get("dialogue") or []:
        if not isinstance(item, Mapping):
            raise AIResponseError("dialogue entries must be objects")
        dialogue.append(DialogueLine(_text(item.get("speaker"), "speaker", max_len=60),
                                     _text(item.get("text"), "dialogue text", max_len=600)))
    actions = []
    for item in data.get("actions") or []:
        if not isinstance(item, Mapping):
            raise AIResponseError("actions must be objects")
        actions.append(SceneAction(_text(item.get("id"), "action id", max_len=60),
                                   _text(item.get("label"), "action label", max_len=120)))
    if not actions:
        raise AIResponseError("scene has no actions")
    return StoryScene(
        scene_title=_text(data.get("scene_title"), "scene_title", max_len=120),
        scene_description=_text(data.get("scene_description"), "scene_description", max_len=3000),
        dialogue=dialogue,
        actions=actions,
        consequence_preview=_text(data.get("consequence_preview"), "consequence_preview", required=False),
        characters=_str_list(data.get("characters"), "characters"),
        event_category=_text(data.get("event_category") or "story", "event_category", max_len=60),
    )


def parse_review(raw: Any) -> ReviewResult:
    data = load_json_object(raw)
    approved = data.get("approved")
    if not isinstance(approved, bool):
        raise AIResponseError("review 'approved' must be true or false")
    return ReviewResult(
        approved=approved,
        issues=_str_list(data.get("issues"), "issues"),
        corrections=_str_list(data.get("corrections"), "corrections"),
        requires_retry=bool(data.get("requires_retry", False)),
    )
