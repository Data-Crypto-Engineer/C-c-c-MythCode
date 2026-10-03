"""Creating, serialising and loading game state. State is a plain dict stored in st.session_state."""
import copy
import json
import uuid
from dataclasses import asdict

from core.learning_engine import normalize_learning
from core.quest_manager import GameContent
from core.state_validator import validate_world_state
from models.learning import LearningProgress
from models.player import PlayerProfile
from utils.error_handler import StateValidationError, StorageError
from utils.validators import validate_character

SAVE_VERSION = 1
START_SCENE = "start"
MAX_HISTORY = 50


def new_game_state(name: str, role: str, style: str, content: GameContent) -> dict:
    name, role, style = validate_character(name, role, style)
    return {
        "version": SAVE_VERSION,
        "session_id": str(uuid.uuid4()),
        "turn": 0,
        "scene_id": START_SCENE,
        "player": asdict(PlayerProfile(name=name, role=role, style=style)),
        "world": copy.deepcopy(content.initial_world),
        "learning": asdict(LearningProgress()),
        "history": [],  # recent window of {"turn","scene","choice"}
    }


def state_to_json(state: dict) -> str:
    try:
        return json.dumps(state, indent=2)
    except (TypeError, ValueError) as exc:
        raise StorageError("Game state could not be saved.") from exc


def state_from_json(text, content: GameContent) -> dict:
    """Parse and fully validate a saved game. Raises StorageError for anything unusable."""
    try:
        state = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise StorageError("The file is not valid JSON.") from exc
    if not isinstance(state, dict) or state.get("version") != SAVE_VERSION:
        raise StorageError("This is not a MythCode save (or it is from an incompatible version).")
    for key in ("session_id", "turn", "scene_id", "player", "world", "learning", "history"):
        if key not in state:
            raise StorageError(f"Save file is missing '{key}'.")
    if state["scene_id"] not in content.scenes:
        raise StorageError("Save file points to an unknown scene.")
    if not isinstance(state["turn"], int) or not isinstance(state["history"], list):
        raise StorageError("Save file has malformed progress data.")
    player = state["player"]
    try:
        validate_character(player.get("name"), player.get("role"), player.get("style"))
    except Exception as exc:
        raise StorageError("Save file has an invalid character.") from exc
    problems = validate_world_state(state["world"], content.locations, content.quests)
    if problems:
        raise StorageError("Save file world data is invalid: " + problems[0])
    state["learning"] = normalize_learning(state["learning"])  # fills new fields; raises StorageError if impossible
    return state
