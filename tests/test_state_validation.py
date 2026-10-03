import copy

from core.quest_manager import load_content
from core.state_validator import apply_effects, validate_world_state
from utils.error_handler import StateValidationError

C = load_content()
KW = dict(locations=C.locations, npcs=C.npcs, quests=C.quests)


def world():
    return copy.deepcopy(C.initial_world)


def rejects(effects, w=None):
    w = w or world()
    before = copy.deepcopy(w)
    try:
        apply_effects(w, effects, **KW)
    except StateValidationError:
        assert w == before  # input untouched (rollback)
        return True
    return False


def test_initial_world_is_valid():
    assert validate_world_state(world(), C.locations, C.quests) == []


def test_valid_change_applies():
    new, _ = apply_effects(world(), {"discover": ["old_waterwheel"], "move_to": "old_waterwheel",
                                     "add": {"village_morale": 10}, "set": {"water_supply": "damaged"}}, **KW)
    assert new["current_location"] == "old_waterwheel" and new["village_morale"] == 70
    assert new["water_supply"] == "damaged"


def test_rejects_nonexistent_location():
    assert rejects({"discover": ["moon_base"]})
    assert rejects({"move_to": "moon_base"})


def test_rejects_undiscovered_location():
    assert rejects({"move_to": "whispering_forest"})


def test_rejects_unknown_field_and_effect():
    assert rejects({"set": {"village_morale": 5}})
    assert rejects({"teleport": True})


def test_rejects_bad_values():
    assert rejects({"set": {"water_supply": "overflowing"}})
    assert rejects({"add": {"village_morale": "lots"}})
    assert rejects({"add": {"village_morale": True}})


def test_numbers_are_clamped_with_note():
    new, notes = apply_effects(world(), {"add": {"village_morale": 500}}, **KW)
    assert new["village_morale"] == 100 and notes


def test_duplicate_quest_completion_rejected():
    w, _ = apply_effects(world(), {"complete_quest": "water_crisis"}, **KW)
    assert rejects({"complete_quest": "water_crisis"}, w)


def test_water_cannot_regress():
    w, _ = apply_effects(world(), {"set": {"water_supply": "restored"}}, **KW)
    assert rejects({"set": {"water_supply": "damaged"}}, w)


def test_previous_decisions_preserved():
    w, _ = apply_effects(world(), {"record_choice": {"id": "a", "text": "First."}}, **KW)
    w2, _ = apply_effects(w, {"record_choice": {"id": "b", "text": "Second."}}, **KW)
    assert [c["id"] for c in w2["important_choices"]] == ["a", "b"]


def test_contradictory_memory_rejected():
    w, _ = apply_effects(world(), {"remember": {"mira": {"t": "One."}}}, **KW)
    assert rejects({"remember": {"mira": {"t": "Different."}}}, w)
    assert rejects({"remember": {"ghost": {"t": "x"}}})


def test_failed_batch_changes_nothing():
    # one valid part + one invalid part must not partially apply
    assert rejects({"add": {"village_morale": 10}, "move_to": "moon_base"})


def test_corrupted_world_detected():
    w = world()
    w["completed_quests"] = ["water_crisis", "water_crisis"]
    assert validate_world_state(w, C.locations, C.quests)


def test_start_quest_only_after_current_quest_is_finished():
    assert rejects({"start_quest": "guardian_trial"})  # water_crisis still unresolved
    w = world()
    new, _ = apply_effects(w, {"complete_quest": "water_crisis", "start_quest": "guardian_trial"}, **KW)
    assert new["active_quest"] == "guardian_trial" and new["completed_quests"] == ["water_crisis"]


def test_start_quest_rejects_unknown_or_completed():
    w = world()
    w["completed_quests"] = ["water_crisis"]
    assert rejects({"start_quest": "dragon_hunt"}, w)
    assert rejects({"start_quest": "water_crisis"}, w)
