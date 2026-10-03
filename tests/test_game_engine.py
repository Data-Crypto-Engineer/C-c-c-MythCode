import json

from core.game_engine import apply_choice, get_scene_view
from core.quest_manager import load_content
from core.state_manager import new_game_state, state_from_json, state_to_json
from utils.error_handler import StorageError
from utils.validators import InputError, validate_character

C = load_content()


def test_new_game_initialisation():
    s = new_game_state("Aria", "Tinkerer", "Puzzles", C)
    assert s["scene_id"] == "start" and s["turn"] == 0 and s["player"]["name"] == "Aria"
    assert s["world"]["water_supply"] == "stopped" and s["world"]["completed_quests"] == []
    assert set(s["learning"]["concepts"]) == {"sequence", "conditions", "loops"}


def test_character_creation_validation():
    assert validate_character("  Aria   Vale ", "Healer", "Balanced")[0] == "Aria Vale"
    for bad in ("", "   ", "x" * 40, "<script>"):
        try:
            validate_character(bad, "Healer", "Balanced")
            assert False, bad
        except InputError:
            pass
    try:
        validate_character("Aria", "Dragon", "Balanced")
        assert False
    except InputError:
        pass


def test_opening_scene_has_three_pathways():
    s = new_game_state("Aria", "Scout", "Balanced", C)
    assert len(get_scene_view(s, C)["choices"]) == 3


def play(path):
    s = new_game_state("Aria", "Scout", "Balanced", C)
    for cid in path:
        s, err = apply_choice(s, cid, C)
        assert err is None, (cid, err)
    return s


def test_all_three_pathways_complete():
    for path in (["go_waterwheel", "repair_gears", "wheel_install"],
                 ["go_spirit", "offer_seed", "protect_river"],
                 ["go_underground", "dig_careful", "channel_well"]):
        s = play(path)
        assert s["world"]["completed_quests"] == ["water_crisis"]
        assert s["world"]["water_supply"] == "restored"
        assert get_scene_view(s, C)["is_end"]


def test_choices_leave_persistent_traces():
    s = play(["go_waterwheel", "repair_gears"])
    assert [c["id"] for c in s["world"]["important_choices"]] == ["path_waterwheel", "wheel_repair"]
    assert "helped_repair" in s["world"]["character_memories"]["mira"]


def test_memory_changes_dialogue():
    helped = get_scene_view(play(["go_waterwheel", "repair_gears"]), C)["dialogue"][0][1]
    forced = get_scene_view(play(["go_waterwheel", "force_wheel"]), C)["dialogue"][0][1]
    assert helped != forced and "patient" in helped


def test_epilogue_references_past_choice():
    s = play(["go_waterwheel", "repair_gears", "wheel_install"])
    lines = dict(get_scene_view(s, C)["dialogue"])
    assert "rebuild" in lines["Mira"]
    assert "Lumen" not in lines  # never met on this path


def test_invalid_choice_keeps_state():
    s = new_game_state("Aria", "Scout", "Balanced", C)
    s2, err = apply_choice(s, "not_a_choice", C)
    assert s2 is s and err


def test_failed_validation_keeps_state():
    s = new_game_state("Aria", "Scout", "Balanced", C)
    scene = C.scenes["start"]
    original = scene["choices"][0]["effects"]["discover"]
    scene["choices"][0]["effects"]["discover"] = ["moon_base"]  # simulate a bad proposal
    try:
        s2, err = apply_choice(s, "go_waterwheel", C)
    finally:
        scene["choices"][0]["effects"]["discover"] = original
    assert s2 is s and err and s2["scene_id"] == "start" and s2["turn"] == 0


def test_save_and_reload_round_trip():
    s = play(["go_spirit", "offer_seed"])
    s2 = state_from_json(state_to_json(s), C)
    assert s2 == s


def test_corrupted_saves_rejected():
    s = play(["go_spirit"])
    bad = json.loads(state_to_json(s))
    bad["world"]["water_supply"] = "lava"
    for text in ("not json", "[]", json.dumps({"version": 99}), json.dumps(bad)):
        try:
            state_from_json(text, C)
            assert False, text
        except StorageError:
            pass
