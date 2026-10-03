import copy
import json

from core.game_engine import apply_choice, get_scene_view, request_hint, submit_puzzle
from core.learning_engine import (
    evaluate_puzzle, next_recommendation, normalize_learning, record_attempt, record_hint, understanding,
)
from core.quest_manager import check_content, load_content
from core.state_manager import new_game_state, state_from_json, state_to_json
from models.learning import CONCEPTS, LearningProgress
from utils.error_handler import PuzzleInputError, StorageError
from dataclasses import asdict

C = load_content()
SEQ, COND, LOOP = (C.puzzles[k] for k in ("sequence_room", "conditions_door", "loops_path"))
GOOD_SEQ = ["forward", "forward", "turn_right", "forward"]
GOOD_RULE = {"condition": "has_key", "then": "open_door", "else": "search_for_key"}


def raises_input(puzzle, submission):
    try:
        evaluate_puzzle(puzzle, submission)
    except PuzzleInputError:
        return True
    return False


# ---------------------------------------------------------------- sequence
def test_sequence_correct_solution():
    r = evaluate_puzzle(SEQ, GOOD_SEQ)
    assert r["solved"] and r["trace"][-1] == {"x": 2, "y": 1, "facing": "south"}


def test_sequence_order_matters():
    # same instructions, different order -> different outcome
    assert not evaluate_puzzle(SEQ, ["forward", "turn_right", "forward", "forward"])["solved"]
    assert not evaluate_puzzle(SEQ, ["turn_right", "forward", "forward", "forward"])["solved"]


def test_sequence_wall_and_edge_stop_the_guardian():
    wall = evaluate_puzzle(SEQ, ["turn_right", "forward", "turn_left", "forward"])  # (0,1) then into block (1,1)
    assert not wall["solved"] and wall["bumped_at"] == 4 and "stone block" in wall["feedback"]
    edge = evaluate_puzzle(SEQ, ["turn_left", "forward"])  # facing north at the top row
    assert not edge["solved"] and edge["bumped_at"] == 2 and "edge" in edge["feedback"]


def test_sequence_passing_the_goal_is_not_a_solution():
    assert not evaluate_puzzle(SEQ, GOOD_SEQ + ["forward"])["solved"]


def test_sequence_extra_turns_that_cancel_out_still_solve():
    assert evaluate_puzzle(SEQ, ["turn_left", "turn_right"] + GOOD_SEQ)["solved"]  # judged by simulation, not by pattern


def test_sequence_malformed_submissions_are_input_errors():
    assert raises_input(SEQ, [])
    assert raises_input(SEQ, "forward")
    assert raises_input(SEQ, ["forward", "fly"])
    assert raises_input(SEQ, [["forward"]])
    assert raises_input(SEQ, ["forward"] * 9)


# ---------------------------------------------------------------- conditions
def test_condition_correct_rule():
    r = evaluate_puzzle(COND, GOOD_RULE)
    assert r["solved"] and all(t["ok"] for t in r["trace"])


def test_condition_logically_equivalent_rule_also_solves():
    assert evaluate_puzzle(COND, {"condition": "no_key", "then": "search_for_key", "else": "open_door"})["solved"]


def test_condition_wrong_rules_fail():
    swapped = evaluate_puzzle(COND, {"condition": "has_key", "then": "search_for_key", "else": "open_door"})
    assert not swapped["solved"] and "should" in swapped["feedback"]
    # 'door is locked' is true in both situations, so it cannot tell them apart
    assert not evaluate_puzzle(COND, {"condition": "door_locked", "then": "open_door", "else": "search_for_key"})["solved"]
    assert not evaluate_puzzle(COND, {"condition": "has_key", "then": "open_door", "else": "wait"})["solved"]


def test_condition_malformed_submissions_are_input_errors():
    assert raises_input(COND, None)
    assert raises_input(COND, {"condition": "", "then": "open_door", "else": "wait"})
    assert raises_input(COND, {"condition": "has_key", "then": "explode", "else": "wait"})
    assert raises_input(COND, {"condition": "has_key", "then": "open_door"})
    assert raises_input(COND, {"condition": ["has_key"], "then": "open_door", "else": "wait"})


# ---------------------------------------------------------------- loops
def test_loop_solutions():
    assert evaluate_puzzle(LOOP, [{"op": "repeat", "times": 5}])["solved"]
    assert evaluate_puzzle(LOOP, [{"op": "forward"}, {"op": "repeat", "times": 4}])["solved"]
    assert evaluate_puzzle(LOOP, [{"op": "repeat", "times": 2}, {"op": "repeat", "times": 3}])["solved"]


def test_loop_wrong_step_counts_fail():
    short = evaluate_puzzle(LOOP, [{"op": "repeat", "times": 3}])
    assert not short["solved"] and "tile 3" in short["feedback"]
    over = evaluate_puzzle(LOOP, [{"op": "repeat", "times": 6}])
    assert not over["solved"] and over["bumped_at"] == 6 and "river" in over["feedback"]
    assert not evaluate_puzzle(LOOP, [{"op": "forward"}, {"op": "forward"}])["solved"]


def test_loop_malformed_submissions_are_input_errors():
    assert raises_input(LOOP, [])
    assert raises_input(LOOP, [{"op": "forward"}] * 3)  # memory holds only 2
    assert raises_input(LOOP, [{"op": "repeat", "times": 0}])
    assert raises_input(LOOP, [{"op": "repeat", "times": 10}])
    assert raises_input(LOOP, [{"op": "repeat", "times": True}])
    assert raises_input(LOOP, [{"op": "repeat", "times": "5"}])
    assert raises_input(LOOP, [{"op": "teleport"}])
    assert raises_input(LOOP, ["forward"])


def test_code_strings_are_never_executed():
    # A submission is data only; there is no eval/exec path. This must be rejected, not run.
    assert raises_input(SEQ, ["__import__('os').system('echo hi')"])
    assert raises_input(COND, {"condition": "__import__('os')", "then": "open_door", "else": "wait"})


# ---------------------------------------------------------------- learning progress
def fresh():
    return asdict(LearningProgress())


def test_failed_attempt_never_unlocks_python():
    l = record_attempt(fresh(), "sequence", False)
    p = l["concepts"]["sequence"]
    assert p["attempts"] == 1 and p["introduced"] and not p["solved"] and not p["python_unlocked"]


def test_solve_unlocks_python_and_records_effort():
    l = record_hint(fresh(), "loops")
    l = record_attempt(l, "loops", False)
    l = record_attempt(l, "loops", True)
    p = l["concepts"]["loops"]
    assert p["solved"] and p["python_unlocked"] and p["attempts_to_solve"] == 2 and p["hints_at_solve"] == 1
    assert understanding(p) == "supported"
    assert not l["concepts"]["sequence"]["solved"]  # other concepts untouched


def test_later_failures_do_not_unsolve_or_rewrite_first_solve():
    l = record_attempt(fresh(), "conditions", True)
    l = record_attempt(l, "conditions", False)
    p = l["concepts"]["conditions"]
    assert p["solved"] and p["python_unlocked"] and p["attempts"] == 2 and p["attempts_to_solve"] == 1
    assert understanding(p) == "independent"


def test_record_functions_do_not_mutate_input():
    original = fresh()
    snapshot = copy.deepcopy(original)
    record_attempt(original, "sequence", True)
    record_hint(original, "sequence")
    assert original == snapshot


def test_recommendation_follows_real_outcomes():
    l = fresh()
    assert next_recommendation(l)["concept"] == "sequence"
    l = record_attempt(l, "sequence", True)
    assert next_recommendation(l)["concept"] == "conditions"
    for c in CONCEPTS:
        l = record_attempt(l, c, True)
    assert next_recommendation(l)["concept"] is None


def test_normalize_learning_upgrades_phase1_saves_and_rejects_impossible_data():
    old = {"concepts": {c: {"introduced": False, "attempts": 0, "solved": False, "hints_used": 0,
                            "python_unlocked": False} for c in CONCEPTS}}
    assert normalize_learning(old)["concepts"]["loops"]["attempts_to_solve"] == 0
    cheated = fresh()
    cheated["concepts"]["loops"]["python_unlocked"] = True  # unlocked but never solved
    for bad in (cheated, {"concepts": []}, None):
        try:
            normalize_learning(bad)
            assert False
        except StorageError:
            pass
    negative = fresh()
    negative["concepts"]["loops"]["attempts"] = -1
    try:
        normalize_learning(negative)
        assert False
    except StorageError:
        pass


# ---------------------------------------------------------------- engine integration
def at_guardian_puzzle():
    s = new_game_state("Aria", "Scout", "Balanced", C)
    for cid in ("go_waterwheel", "repair_gears", "wheel_install", "visit_workshop", "help_guardian"):
        s, err = apply_choice(s, cid, C)
        assert err is None, (cid, err)
    return s


def test_content_data_is_consistent():
    assert check_content(C) == []


def test_puzzle_scene_marks_concept_encountered_only_on_arrival():
    s = new_game_state("Aria", "Scout", "Balanced", C)
    assert not s["learning"]["concepts"]["sequence"]["introduced"]
    assert at_guardian_puzzle()["learning"]["concepts"]["sequence"]["introduced"]


def test_python_reveal_only_after_real_solve():
    s = at_guardian_puzzle()
    assert get_scene_view(s, C)["reveal"] is None
    s, r = submit_puzzle(s, GOOD_SEQ, C)
    assert r["solved"]
    reveal = get_scene_view(s, C)["reveal"]
    assert reveal and reveal["python"].startswith("move_forward()")


def test_wrong_answer_counts_attempt_but_keeps_scene_and_world():
    s = at_guardian_puzzle()
    s2, r = submit_puzzle(s, ["forward"], C)
    assert r["valid"] and not r["solved"]
    assert s2["scene_id"] == s["scene_id"] and s2["world"] == s["world"] and s2["turn"] == s["turn"]
    assert s2["learning"]["concepts"]["sequence"]["attempts"] == 1
    assert s["learning"]["concepts"]["sequence"]["attempts"] == 0  # original untouched
    assert not s2["learning"]["concepts"]["sequence"]["python_unlocked"]


def test_malformed_submission_is_not_an_attempt():
    s = at_guardian_puzzle()
    s2, r = submit_puzzle(s, [], C)
    assert not r["valid"] and s2 is s
    s3, r3 = submit_puzzle(s, ["fly"], C)
    assert not r3["valid"] and s3 is s


def test_submit_on_non_puzzle_scene_changes_nothing():
    s = new_game_state("Aria", "Scout", "Balanced", C)
    s2, r = submit_puzzle(s, GOOD_SEQ, C)
    assert s2 is s and not r["valid"]


def test_hints_are_counted_in_order_and_run_out():
    s = at_guardian_puzzle()
    shown = []
    for _ in range(3):
        s, hint = request_hint(s, C)
        shown.append(hint)
    assert shown == SEQ["hints"] and s["learning"]["concepts"]["sequence"]["hints_used"] == 3
    s2, hint = request_hint(s, C)
    assert hint is None and s2 is s
    view = get_scene_view(s, C)["puzzle"]
    assert view["hints_shown"] == SEQ["hints"] and view["hints_total"] == 3


def test_full_guardian_arc_with_progress_and_world_changes():
    s = at_guardian_puzzle()
    s, r = submit_puzzle(s, GOOD_SEQ, C)
    assert s["world"]["clockwork_guardian"] == "awakened" and s["world"]["active_quest"] == "guardian_trial"
    s, _ = apply_choice(s, "to_cellar", C)
    s, r = submit_puzzle(s, {"condition": "has_key", "then": "search_for_key", "else": "open_door"}, C)  # wrong first
    assert not r["solved"] and s["scene_id"] == "guardian_door"
    s, r = submit_puzzle(s, GOOD_RULE, C)
    assert r["solved"]
    s, _ = apply_choice(s, "to_river", C)
    s, r = submit_puzzle(s, [{"op": "repeat", "times": 5}], C)
    assert r["solved"] and get_scene_view(s, C)["is_end"]
    assert s["world"]["clockwork_guardian"] == "guarding"
    assert s["world"]["completed_quests"] == ["water_crisis", "guardian_trial"]
    c = s["learning"]["concepts"]
    assert all(c[k]["solved"] and c[k]["python_unlocked"] for k in CONCEPTS)
    assert c["conditions"]["attempts"] == 2 and c["conditions"]["attempts_to_solve"] == 2
    assert understanding(c["sequence"]) == "independent"
    tail = [h["choice"] for h in s["history"]][-6:]
    assert tail == ["help_guardian", "solved:sequence_room", "to_cellar", "solved:conditions_door",
                    "to_river", "solved:loops_path"]
    assert "Mira" in dict(get_scene_view(s, C)["dialogue"])


def test_all_three_water_pathways_lead_into_the_guardian_quest():
    for path in (["go_waterwheel", "repair_gears", "wheel_install"],
                 ["go_spirit", "offer_seed", "protect_river"],
                 ["go_underground", "dig_careful", "channel_well"]):
        s = new_game_state("Aria", "Scout", "Balanced", C)
        for cid in path + ["visit_workshop", "help_guardian"]:
            s, err = apply_choice(s, cid, C)
            assert err is None, (path, cid, err)
        assert s["scene_id"] == "guardian_seq" and s["world"]["current_location"] == "mira_workshop"


def test_failed_solve_effects_roll_back_everything():
    s = at_guardian_puzzle()
    scene = C.scenes["guardian_seq"]
    original = scene["on_solve"]["effects"]
    scene["on_solve"]["effects"] = {"set": {"water_supply": "stopped"}}  # water may not get worse
    try:
        s2, r = submit_puzzle(s, GOOD_SEQ, C)
    finally:
        scene["on_solve"]["effects"] = original
    assert s2 is s and not r["solved"]
    assert s["learning"]["concepts"]["sequence"]["attempts"] == 0 and s["scene_id"] == "guardian_seq"


def test_mid_puzzle_save_round_trip_keeps_progress():
    s = at_guardian_puzzle()
    s, _ = request_hint(s, C)
    s, _ = submit_puzzle(s, ["forward"], C)
    s2 = state_from_json(state_to_json(s), C)
    assert s2 == s and s2["learning"]["concepts"]["sequence"]["hints_used"] == 1


def test_phase1_style_save_still_loads():
    s = new_game_state("Aria", "Scout", "Balanced", C)
    data = json.loads(state_to_json(s))
    for p in data["learning"]["concepts"].values():
        del p["attempts_to_solve"], p["hints_at_solve"]
    loaded = state_from_json(json.dumps(data), C)
    assert loaded["learning"]["concepts"]["sequence"]["hints_at_solve"] == 0


def test_tampered_save_cannot_unlock_python_without_solving():
    s = at_guardian_puzzle()
    data = json.loads(state_to_json(s))
    data["learning"]["concepts"]["loops"]["python_unlocked"] = True
    try:
        state_from_json(json.dumps(data), C)
        assert False
    except StorageError:
        pass
