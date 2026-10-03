"""Loads static game content (locations, NPCs, quests, fallback scenes) and summarises quest state."""
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from models.character import Npc
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


@lru_cache(maxsize=1)
def load_content() -> GameContent:
    try:
        world = json.loads((DATA_DIR / "initial_world.json").read_text(encoding="utf-8"))
        quests = json.loads((DATA_DIR / "quests.json").read_text(encoding="utf-8"))
        return GameContent(
            locations=world["locations"],
            npcs={k: Npc(id=k, **v) for k, v in world["npcs"].items()},
            quests={k: Quest(id=k, **v) for k, v in quests["quests"].items()},
            scenes=quests["scenes"],
            initial_world=world["initial_state"],
        )
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise StorageError(f"Game data files are missing or damaged ({type(exc).__name__}).") from exc


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
