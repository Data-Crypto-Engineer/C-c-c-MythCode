"""Loads static game content (locations, NPCs, quests, fallback scenes) and summarises quest state."""
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from core.state_validator import ALLOWED_EFFECT_KEYS
from models.character import Npc
from models.learning import CONCEPTS
from models.quest import Quest
from utils.error_handler import StorageError

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@dataclass(frozen=True)
class GameContent:
    locations: dict   # id -> {"name","description"}
    npcs: dict        # id -> Npc
    quests: dict      # id -> Quest
    scenes: dict      # id -> scene dict
    initial_world: dict
    puzzles: dict     # id -> puzzle dict (data/puzzles.json)


@lru_cache(maxsize=1)
def load_content() -> GameContent:
    try:
        world = json.loads((DATA_DIR / "initial_world.json").read_text(encoding="utf-8"))
        quests = json.loads((DATA_DIR / "quests.json").read_text(encoding="utf-8"))
        puzzles = json.loads((DATA_DIR / "puzzles.json").read_text(encoding="utf-8"))
        content = GameContent(
            locations=world["locations"],
            npcs={k: Npc(id=k, **v) for k, v in world["npcs"].items()},
            quests={k: Quest(id=k, **v) for k, v in quests["quests"].items()},
            scenes=quests["scenes"],
            initial_world=world["initial_state"],
            puzzles=puzzles["puzzles"],
        )
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise StorageError(f"Game data files are missing or damaged ({type(exc).__name__}).") from exc
    problems = check_content(content)
    if problems:
        raise StorageError("Game data is inconsistent: " + problems[0])
    return content


def check_content(content: GameContent) -> list:
    """Structural checks on the static game data (links between scenes, puzzles, NPCs). Empty list = OK."""
    issues = []

    def check_effects(where: str, effects: dict):
        for key in effects:
            if key not in ALLOWED_EFFECT_KEYS:
                issues.append(f"{where}: unknown effect '{key}'.")
        for loc in list(effects.get("discover", [])) + ([effects["move_to"]] if "move_to" in effects else []):
            if loc not in content.locations:
                issues.append(f"{where}: unknown location '{loc}'.")
        for npc in effects.get("remember", {}):
            if npc not in content.npcs:
                issues.append(f"{where}: unknown character '{npc}'.")
        for key in ("complete_quest", "start_quest"):
            if key in effects and effects[key] not in content.quests:
                issues.append(f"{where}: unknown quest '{effects[key]}'.")

    for sid, scene in content.scenes.items():
        for entry in scene.get("dialogue", []):
            if entry["npc"] not in content.npcs:
                issues.append(f"Scene '{sid}': unknown character '{entry['npc']}'.")
        for c in scene.get("choices", []):
            if c["next"] not in content.scenes:
                issues.append(f"Scene '{sid}': choice '{c['id']}' leads to unknown scene '{c['next']}'.")
            check_effects(f"Scene '{sid}' choice '{c['id']}'", c.get("effects", {}))
        puzzle_id = scene.get("puzzle")
        if puzzle_id is not None:
            if puzzle_id not in content.puzzles:
                issues.append(f"Scene '{sid}': unknown puzzle '{puzzle_id}'.")
            solve = scene.get("on_solve")
            if scene.get("choices") or not solve:
                issues.append(f"Scene '{sid}': a puzzle scene needs 'on_solve' and no choices.")
            else:
                if solve["next"] not in content.scenes:
                    issues.append(f"Scene '{sid}': on_solve leads to unknown scene '{solve['next']}'.")
                check_effects(f"Scene '{sid}' on_solve", solve.get("effects", {}))
        reveal = scene.get("reveal")
        if reveal is not None and reveal not in CONCEPTS:
            issues.append(f"Scene '{sid}': unknown reveal concept '{reveal}'.")
    for pid, puzzle in content.puzzles.items():
        if puzzle.get("concept") not in CONCEPTS:
            issues.append(f"Puzzle '{pid}': unknown concept.")
        if not puzzle.get("hints") or not puzzle.get("reveal", {}).get("python"):
            issues.append(f"Puzzle '{pid}': needs hints and a Python reveal.")
    return issues


def quest_summary(world: dict, content: GameContent) -> dict:
    """Data for the Quest Journal tab."""
    active = content.quests.get(world.get("active_quest"))
    completed = [content.quests[q].title for q in world["completed_quests"] if q in content.quests]
    discoveries = [content.locations[l]["name"] for l in world["discovered_locations"] if l in content.locations]
    unresolved = []
    if active and active.id not in world["completed_quests"]:
        unresolved.append(active.title)
    return {
        "current": None if (active is None or active.id in world["completed_quests"]) else active,
        "completed": completed,
        "choices": [c["text"] for c in world["important_choices"]],
        "discoveries": discoveries,
        "unresolved": unresolved,
    }
