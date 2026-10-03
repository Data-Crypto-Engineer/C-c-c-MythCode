"""Phase 3 tests. Plain unittest style, so they run with `pytest` or `python -m unittest`.
No real API calls and no CrewAI import are needed: model output is mocked."""
import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import (continuity_safety_agent as safety, director_agent, logic_learning_agent as learning,
                    player_insight_agent as insight, story_weaver_agent as weaver, world_keeper_agent as keeper)
from agents.mythcode_crew import CrewRequest, process_player_action
from agents.prompt_utils import render_context
from agents.schemas import (WorldDelta, parse_director_plan, parse_story_scene)
from utils.ai_errors import (AIResponseError, ConfigError, ErrorKind, call_with_retries, classify_exception,
                             redact)
from utils.llm_config import LLMSettings, apply_to_environment, load_llm_settings, try_load_settings

FAKE_KEY = "AIzaSyFAKEKEYFORTESTS000000000000000"


def make_world():
    return {"kingdom": "Elarion", "current_location": "Whispering Village",
            "valid_locations": ["Whispering Village", "Mira's Workshop", "River Bend"],
            "discovered_locations": ["Whispering Village"], "water_supply": "damaged",
            "forest_spirit_trust": 0, "clockwork_guardian": "inactive", "village_morale": 60,
            "completed_quests": [], "important_choices": [], "npcs": ["Mira", "Elder Bram"],
            "character_memories": {}}


def good_scene(**over):
    data = {"scene_title": "Rain on the Wheel", "scene_description": "Mira waves you over to the old waterwheel.",
            "dialogue": [{"speaker": "Mira", "text": "It stopped turning last night."}],
            "actions": [{"id": "inspect_wheel", "label": "Inspect the wheel"},
                        {"id": "ask_mira", "label": "Ask Mira more"}],
            "consequence_preview": "", "characters": ["Mira"], "event_category": "story"}
    data.update(over)
    return json.dumps(data)


def settings(**over):
    base = dict(api_key=FAKE_KEY, model="gemini/test-model", max_retries=2)
    base.update(over)
    return LLMSettings(**base)


class ConfigTests(unittest.TestCase):
    def test_missing_key_raises_config_error(self):
        with self.assertRaises(ConfigError):
            load_llm_settings({}, {})

    def test_missing_model_raises_config_error(self):
        with self.assertRaises(ConfigError):
            load_llm_settings({"GEMINI_API_KEY": FAKE_KEY}, {})

    def test_placeholder_key_is_treated_as_missing(self):
        with self.assertRaises(ConfigError):
            load_llm_settings({"GEMINI_API_KEY": "YOUR_API_KEY", "GEMINI_MODEL": "m"}, {})

    def test_top_level_and_section_layouts_both_work(self):
        a = load_llm_settings({"GEMINI_API_KEY": FAKE_KEY, "GEMINI_MODEL": "flash-x"}, {})
        b = load_llm_settings({"llm": {"api_key": FAKE_KEY, "model": "models/flash-x"}}, {})
        self.assertEqual(a.model, "gemini/flash-x")
        self.assertEqual(b.model, "gemini/flash-x")

    def test_malformed_secrets_object_does_not_crash(self):
        class Broken:
            def __getitem__(self, key):
                raise RuntimeError("no secrets file")
        settings_, message = try_load_settings(Broken(), {})
        self.assertIsNone(settings_)
        self.assertIn("not set up", message)

    def test_key_is_not_in_repr_or_error_text(self):
        s = load_llm_settings({"GEMINI_API_KEY": FAKE_KEY, "GEMINI_MODEL": "m"}, {})
        self.assertNotIn(FAKE_KEY, repr(s))
        self.assertNotIn(FAKE_KEY, redact(f"failed with key {FAKE_KEY}", [FAKE_KEY]))

    def test_apply_to_environment(self):
        env = {}
        apply_to_environment(settings(), env)
        self.assertEqual(env["GEMINI_API_KEY"], FAKE_KEY)


class ErrorHandlingTests(unittest.TestCase):
    def test_classification(self):
        self.assertEqual(classify_exception(Exception("429 RESOURCE_EXHAUSTED quota")), ErrorKind.RATE_LIMIT)
        self.assertEqual(classify_exception(Exception("API key not valid")), ErrorKind.AUTH)
        self.assertEqual(classify_exception(TimeoutError("timed out")), ErrorKind.TIMEOUT)
        self.assertEqual(classify_exception(Exception("503 service unavailable")), ErrorKind.SERVER)
        self.assertEqual(classify_exception(AIResponseError("x")), ErrorKind.BAD_RESPONSE)

    def test_auth_errors_are_never_retried(self):
        calls = []
        def boom():
            calls.append(1)
            raise Exception("401 unauthorized: API key not valid")
        with self.assertRaises(Exception):
            call_with_retries(boom, max_retries=3, sleep=lambda s: None)
        self.assertEqual(len(calls), 1)

    def test_retryable_errors_are_bounded(self):
        calls = []
        def boom():
            calls.append(1)
            raise Exception("429 rate limit")
        with self.assertRaises(Exception):
            call_with_retries(boom, max_retries=2, sleep=lambda s: None)
        self.assertEqual(len(calls), 3)  # first try + 2 retries, then stop

    def test_retry_can_succeed(self):
        state = {"n": 0}
        def flaky():
            state["n"] += 1
            if state["n"] < 2:
                raise Exception("connection reset")
            return "ok"
        self.assertEqual(call_with_retries(flaky, 2, sleep=lambda s: None), "ok")


class ParsingTests(unittest.TestCase):
    def test_valid_scene_with_code_fence(self):
        scene = parse_story_scene("Here you go:\n```json\n" + good_scene() + "\n```")
        self.assertEqual(scene.scene_title, "Rain on the Wheel")

    def test_empty_malformed_and_wrong_shape_are_rejected(self):
        for bad in ("", None, "not json at all", '{"scene_title": "x"', json.dumps({"scene_title": "x"}),
                    good_scene(actions=[]), good_scene(dialogue=["just text"])):
            with self.assertRaises(AIResponseError, msg=str(bad)[:30]):
                parse_story_scene(bad)

    def test_director_plan_parse_and_bad_category(self):
        plan = parse_director_plan(json.dumps({"next_event": "investigate_waterwheel",
                                               "narrative_objective": "Look at the wheel",
                                               "challenge_category": "loops"}))
        self.assertEqual(plan.challenge_category, "loops")
        with self.assertRaises(AIResponseError):
            parse_director_plan(json.dumps({"next_event": "a", "narrative_objective": "b",
                                            "challenge_category": "recursion"}))

    def test_prompts_never_contain_curly_braces(self):
        ctx = {"note": "has {braces} inside", "nested": {"list": ["{a}", "b"]}}
        self.assertNotIn("{", render_context(ctx))
        description, expected = weaver.build_prompt(ctx, ["Fix: {x}"], True)
        for text in (description, expected, director_agent.build_prompt(ctx)[0], director_agent.build_prompt(ctx)[1]):
            self.assertNotIn("{", text)
            self.assertNotIn("}", text)


class WorldKeeperTests(unittest.TestCase):
    def test_valid_change_is_applied_to_a_copy(self):
        world = make_world()
        result = keeper.validate_transition(world, WorldDelta(
            numeric_deltas={"village_morale": 10}, set_values={"water_supply": "repairing"},
            discover_locations=["Mira's Workshop"], new_location="Mira's Workshop",
            add_choices=["Helped Mira"], add_memories={"Mira": ["Player helped repair her workshop"]}))
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.world["village_morale"], 70)
        self.assertEqual(result.world["current_location"], "Mira's Workshop")
        self.assertEqual(world["village_morale"], 60)  # original untouched
        self.assertEqual(keeper.memories_for(result.world, "Mira"), ["Player helped repair her workshop"])

    def test_invalid_changes_are_rejected_and_world_preserved(self):
        bad_deltas = [
            WorldDelta(numeric_deltas={"village_morale": 90}),           # out of range
            WorldDelta(numeric_deltas={"village_morale": 40}),           # step too large
            WorldDelta(numeric_deltas={"gold": 5}),                      # unknown field
            WorldDelta(discover_locations=["Atlantis"]),                 # nonexistent location
            WorldDelta(new_location="River Bend"),                       # not yet discovered
            WorldDelta(set_values={"water_supply": "lava"}),             # invalid value
            WorldDelta(add_memories={"Stranger": ["hi"]}),               # unknown character
        ]
        for delta in bad_deltas:
            world = make_world()
            result = keeper.validate_transition(world, delta)
            self.assertFalse(result.ok, delta)
            self.assertEqual(result.world, make_world())

    def test_no_duplicate_quests_and_no_backwards_state(self):
        world = make_world()
        world["completed_quests"] = ["waterwheel"]
        world["clockwork_guardian"] = "active"
        self.assertFalse(keeper.validate_transition(world, WorldDelta(complete_quests=["waterwheel"])).ok)
        self.assertFalse(keeper.validate_transition(world, WorldDelta(set_values={"clockwork_guardian": "inactive"})).ok)

    def test_previous_choices_are_never_lost_and_memories_are_capped(self):
        world = make_world()
        world["important_choices"] = ["first choice"]
        world = keeper.validate_transition(world, WorldDelta(add_choices=["second"])).world
        self.assertEqual(world["important_choices"], ["first choice", "second"])
        many = WorldDelta(add_memories={"Mira": [f"m{i}" for i in range(12)]})
        world = keeper.validate_transition(world, many).world
        self.assertEqual(len(world["character_memories"]["Mira"]), 8)

    def test_integrity_check_flags_corrupted_save(self):
        broken = make_world()
        broken["village_morale"] = 999
        broken["current_location"] = "Nowhere"
        problems = keeper.check_world_integrity(broken)
        self.assertEqual(len(problems), 2)


class PlayerInsightTests(unittest.TestCase):
    def test_single_action_changes_are_bounded_and_input_not_mutated(self):
        model = insight.default_player_model()
        before = copy.deepcopy(model)
        new = insight.observe(model, {"kind": "puzzle", "success": True, "hints_used": 0, "concept": "sequence"})
        self.assertEqual(model, before)
        self.assertLessEqual(new["puzzle_preference"] - 0.5, insight.PREFERENCE_STEP + 1e-9)
        self.assertAlmostEqual(new["concept_mastery"]["sequence"], 0.2)
        self.assertEqual(new["challenge_level"], 1)

    def test_adaptation_is_reversible(self):
        model = insight.default_player_model()
        for _ in range(10):
            model = insight.observe(model, {"kind": "puzzle", "success": True, "concept": "loops"})
        high = model["puzzle_preference"]
        for _ in range(60):
            model = insight.observe(model, {"kind": "dialogue"})
        self.assertLess(model["puzzle_preference"], high)
        self.assertTrue(all(0.0 <= model[k] <= 1.0 for k in insight.PREFERENCE_KEYS))

    def test_challenge_level_moves_after_window_and_stays_in_range(self):
        model = insight.default_player_model()
        for _ in range(5):
            model = insight.observe(model, {"kind": "puzzle", "success": True, "hints_used": 0, "concept": "sequence"})
        self.assertEqual(model["challenge_level"], 2)
        for _ in range(30):
            model = insight.observe(model, {"kind": "puzzle", "success": False, "concept": "sequence"})
        self.assertEqual(model["challenge_level"], 1)
        self.assertEqual(model["concept_mastery"]["sequence"], 0.0)

    def test_unknown_event_and_describe(self):
        model = insight.default_player_model()
        self.assertEqual(insight.observe(model, {"kind": "???"}), model)
        self.assertIn("no clear preference", insight.describe(model))


class LearningTests(unittest.TestCase):
    def test_progress_and_reveal_only_after_real_success(self):
        progress = learning.new_learning_progress()
        self.assertIsNone(learning.reveal_for(progress, "sequence"))
        progress = learning.record_attempt(progress, "sequence", False, hints_used=1)
        self.assertIsNone(learning.reveal_for(progress, "sequence"))
        self.assertEqual(learning.understanding_level(progress["sequence"]), "practicing")
        progress = learning.record_attempt(progress, "sequence", True, hints_used=0)
        self.assertIn("move_forward()", learning.reveal_for(progress, "sequence")["python"])
        self.assertEqual(progress["sequence"]["attempts"], 2)
        self.assertEqual(progress["sequence"]["hints_used"], 1)
        self.assertEqual(learning.understanding_level(progress["sequence"]), "solved_independently")

    def test_recommended_order_and_unknown_concept(self):
        progress = learning.new_learning_progress()
        self.assertEqual(learning.recommend_next(progress), "sequence")
        for concept in learning.CONCEPTS:
            progress = learning.record_attempt(progress, concept, True)
        self.assertIsNone(learning.recommend_next(progress))
        self.assertEqual(learning.record_attempt(progress, "recursion", True), progress)

    def test_reveals_use_for_loop_not_eval(self):
        self.assertIn("for step in range(5)", learning.PYTHON_REVEALS["loops"])


class SafetyTests(unittest.TestCase):
    def scene(self, **over):
        return parse_story_scene(good_scene(**over))

    def test_good_scene_is_approved(self):
        review = safety.check_scene(self.scene(), make_world(), ["Mira", "Elder Bram"])
        self.assertTrue(review.approved, review.issues)

    def test_problem_scenes_are_flagged(self):
        cases = {
            "gore everywhere": dict(scene_description="Gore covers the floor."),
            "progress claim": dict(scene_description="You have mastered loops!"),
            "code": dict(scene_description="Type for step in range(5): now."),
            "one action": dict(actions=[{"id": "a", "label": "Only choice"}]),
            "dup ids": dict(actions=[{"id": "a", "label": "x"}, {"id": "a", "label": "y"}]),
            "stranger": dict(characters=["Zorblax"], dialogue=[{"speaker": "Zorblax", "text": "Hi"}]),
        }
        for name, over in cases.items():
            review = safety.check_scene(self.scene(**over), make_world(), ["Mira", "Elder Bram"])
            self.assertFalse(review.approved, name)
            self.assertTrue(review.requires_retry, name)

    def test_ai_review_can_only_add_issues(self):
        py_bad = safety.ReviewResult(False, ["bad"], ["Fix: bad"], True)
        ai_ok = safety.ReviewResult(True)
        self.assertFalse(safety.merge_reviews(py_bad, ai_ok).approved)
        ai_bad = safety.ReviewResult(False, ["tone"], ["Fix: tone"], True)
        merged = safety.merge_reviews(safety.ReviewResult(), ai_bad)
        self.assertFalse(merged.approved)
        self.assertIn("tone", merged.issues)


class DirectorTests(unittest.TestCase):
    def test_same_seed_same_plan_and_always_valid(self):
        world, model = make_world(), insight.default_player_model()
        a = director_agent.rule_based_plan({"label": "Look around"}, world, model, seed=7)
        b = director_agent.rule_based_plan({"label": "Look around"}, world, model, seed=7)
        self.assertEqual(a, b)
        for seed in range(30):
            plan = director_agent.rule_based_plan({}, world, model, seed=seed)
            self.assertTrue(director_agent.plan_is_valid(plan, world))

    def test_completed_events_are_excluded_and_all_done_finishes(self):
        world = make_world()
        world["completed_quests"] = ["investigate_waterwheel"]
        for seed in range(30):
            self.assertNotEqual(director_agent.rule_based_plan({}, world, insight.default_player_model(), seed).next_event,
                                "investigate_waterwheel")
        world["completed_quests"] = list(director_agent.QUEST_EVENTS)
        self.assertEqual(director_agent.rule_based_plan({}, world, insight.default_player_model()).next_event, "quest_complete")

    def test_preference_shifts_probability_and_challenge_follows_mastery(self):
        model = insight.default_player_model()
        for _ in range(25):
            model = insight.observe(model, {"kind": "dialogue"})
        picks = [director_agent.rule_based_plan({}, make_world(), model, s).next_event for s in range(200)]
        self.assertGreater(picks.count("negotiate_forest_spirit"), picks.count("inspect_river_machines"))
        self.assertEqual(director_agent.next_challenge(model), "sequence")


class OrchestrationTests(unittest.TestCase):
    def run_action(self, runner, world=None, **kw):
        return process_player_action({"type": "dialogue", "label": "Ask Mira"}, world or make_world(),
                                     insight.default_player_model(), ["Arrived in village"],
                                     settings=kw.pop("settings", settings()), runner=runner,
                                     sleep=lambda s: None, **kw)

    def test_successful_run_uses_ai_scene_and_one_run(self):
        result = self.run_action(lambda s, r: {"director": None, "story": good_scene()})
        self.assertFalse(result.used_fallback)
        self.assertEqual(result.scene.scene_title, "Rain on the Wheel")
        self.assertEqual(result.llm_runs, 1)
        self.assertEqual(result.world["important_choices"], ["Chose: Ask Mira"])
        self.assertEqual(result.player_model["events_observed"], 1)

    def test_missing_credentials_fall_back_without_crashing(self):
        result = process_player_action({"type": "explore"}, make_world(), None, settings=None)
        self.assertTrue(result.used_fallback)
        self.assertEqual(result.scene.event_category, "fallback")
        self.assertEqual(result.world, make_world())
        self.assertTrue(result.notices)

    def test_malformed_output_is_retried_once_then_falls_back_preserving_state(self):
        calls = []
        def runner(s, r):
            calls.append(list(r.corrections))
            return {"director": None, "story": "this is not json"}
        result = self.run_action(runner)
        self.assertEqual(len(calls), 2)                       # bounded: first try + one regeneration
        self.assertTrue(calls[1])                             # corrections were passed on the retry
        self.assertTrue(result.used_fallback)
        self.assertEqual(result.world, make_world())

    def test_unsafe_first_attempt_is_corrected_on_retry(self):
        outputs = iter([good_scene(scene_description="Gore everywhere."), good_scene()])
        result = self.run_action(lambda s, r: {"director": None, "story": next(outputs)})
        self.assertFalse(result.used_fallback)
        self.assertTrue(result.review.approved)

    def test_api_failures_fall_back_and_auth_is_not_retried(self):
        calls = []
        def auth_fail(s, r):
            calls.append(1)
            raise Exception("403 permission denied: API key not valid")
        result = self.run_action(auth_fail)
        self.assertEqual(len(calls), 1)
        self.assertTrue(result.used_fallback)
        self.assertEqual(result.world, make_world())
        self.assertNotIn(FAKE_KEY, " ".join(result.notices))

    def test_rate_limit_retries_are_bounded(self):
        calls = []
        def limited(s, r):
            calls.append(1)
            raise Exception("429 quota exceeded")
        result = self.run_action(limited, settings=settings(max_retries=2))
        self.assertEqual(len(calls), 3)
        self.assertTrue(result.used_fallback)

    def test_invalid_ai_world_change_is_rejected_and_state_preserved(self):
        plan = {"next_event": "investigate_waterwheel", "narrative_objective": "x",
                "proposed_changes": {"numeric_deltas": {"village_morale": 90}}}
        runner = lambda s, r: {"director": json.dumps(plan), "story": good_scene()}
        result = process_player_action({"type": "quest_transition", "label": "Go"}, make_world(),
                                       insight.default_player_model(), settings=settings(), runner=runner,
                                       sleep=lambda s: None)
        self.assertFalse(result.used_fallback)          # scene is fine...
        self.assertEqual(result.world["village_morale"], 60)  # ...but the bad change was not applied
        self.assertTrue(result.world_errors)
        self.assertEqual(result.llm_runs, 1)

    def test_director_picking_unavailable_event_is_ignored(self):
        plan = {"next_event": "invented_event", "narrative_objective": "x"}
        runner = lambda s, r: {"director": json.dumps(plan), "story": good_scene()}
        result = process_player_action({"type": "quest_transition", "label": "Go"}, make_world(),
                                       insight.default_player_model(), settings=settings(), runner=runner,
                                       sleep=lambda s: None)
        self.assertNotEqual(result.plan.next_event, "invented_event")

    def test_director_context_only_sent_for_major_actions(self):
        seen = []
        def runner(s, r):
            seen.append(r.director_context is not None)
            return {"director": None, "story": good_scene()}
        self.run_action(runner)
        process_player_action({"type": "quest_transition", "label": "Go"}, make_world(), None,
                              settings=settings(), runner=runner, sleep=lambda s: None)
        self.assertEqual(seen, [False, True])


if __name__ == "__main__":
    unittest.main()
