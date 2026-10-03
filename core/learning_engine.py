"""Deterministic puzzle validation and learning-progress tracking.

Two rules shape this module:
  * Whether a solution is correct is decided here by simulation. No AI decides it, and no
    player-submitted code is ever executed (there is no eval/exec: a submission is just data
    such as ["forward", "turn_right"] that we step through ourselves).
  * Learning progress is updated only from real puzzle outcomes via record_attempt()/record_hint().

Submission formats (what the UI sends):
  sequence    -> list of action ids, e.g. ["forward", "forward", "turn_right", "forward"]
  conditional -> {"condition": id, "then": id, "else": id}
  loop        -> list of {"op": "forward"} or {"op": "repeat", "times": n}
"""
import copy
from typing import Callable

from models.learning import CONCEPTS, ConceptProgress
from utils.error_handler import PuzzleInputError, StorageError

FACINGS = ("east", "south", "west", "north")  # turn_right moves one step forward in this list
_DELTA = {"east": (1, 0), "south": (0, 1), "west": (-1, 0), "north": (0, -1)}

UNDERSTANDING_LABELS = {
    "not_yet": "Not solved yet",
    "independent": "Solved without hints in two tries or fewer",
    "supported": "Solved with hints or several tries",
}


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# --------------------------------------------------------------------------- puzzle evaluation
def _evaluate_sequence(cfg: dict, program) -> dict:
    allowed = set(cfg["actions"])
    if not isinstance(program, (list, tuple)) or not program:
        raise PuzzleInputError("Add at least one instruction first.")
    if len(program) > cfg["max_instructions"]:
        raise PuzzleInputError(f"The guardian can only remember {cfg['max_instructions']} instructions.")
    if any(not isinstance(a, str) or a not in allowed for a in program):
        raise PuzzleInputError("One of those instructions isn't available.")

    walls = {(w["x"], w["y"]) for w in cfg["walls"]}
    width, height = cfg["width"], cfg["height"]
    x, y, facing = cfg["start"]["x"], cfg["start"]["y"], FACINGS.index(cfg["start"]["facing"])
    trace = [{"x": x, "y": y, "facing": FACINGS[facing]}]
    bumped_at, reason = None, ""

    for i, action in enumerate(program, start=1):
        if action == "forward":
            dx, dy = _DELTA[FACINGS[facing]]
            nx, ny = x + dx, y + dy
            if not (0 <= nx < width and 0 <= ny < height):
                bumped_at, reason = i, "the edge of the room"
                break
            if (nx, ny) in walls:
                bumped_at, reason = i, "the stone block"
                break
            x, y = nx, ny
        elif action == "turn_right":
            facing = (facing + 1) % 4
        else:  # turn_left
            facing = (facing - 1) % 4
        trace.append({"x": x, "y": y, "facing": FACINGS[facing]})

    goal = (cfg["goal"]["x"], cfg["goal"]["y"])
    solved = bumped_at is None and (x, y) == goal
    if solved:
        feedback = "The guardian ends exactly on the pedestal."
    elif bumped_at is not None:
        feedback = f"Instruction {bumped_at} walked the guardian into {reason}, so it stopped there."
    else:
        feedback = f"The guardian finished at column {x + 1}, row {y + 1}, not on the pedestal. Check the order of your instructions."
    return {"solved": solved, "feedback": feedback, "trace": trace, "bumped_at": bumped_at}


def _evaluate_conditional(cfg: dict, rule) -> dict:
    conditions = {c["id"]: c for c in cfg["conditions"]}
    actions = {a["id"]: a for a in cfg["actions"]}
    if not isinstance(rule, dict):
        raise PuzzleInputError("Build a rule first.")
    cond_id, then_id, else_id = rule.get("condition"), rule.get("then"), rule.get("else")
    if not (isinstance(cond_id, str) and cond_id in conditions):
        raise PuzzleInputError("Pick a question for the rule (the IF part).")
    for label, action_id in (("THEN", then_id), ("ELSE", else_id)):
        if not (isinstance(action_id, str) and action_id in actions):
            raise PuzzleInputError(f"Pick an action for the {label} part.")

    cond = conditions[cond_id]
    trace, first_failure = [], None
    for scenario in cfg["scenarios"]:
        condition_true = bool(scenario["facts"][cond["var"]]) != bool(cond["negate"])
        chosen = then_id if condition_true else else_id
        ok = chosen == scenario["expected"]
        trace.append({
            "label": scenario["label"], "condition_true": condition_true,
            "action": actions[chosen]["label"], "expected": actions[scenario["expected"]]["label"], "ok": ok,
        })
        if not ok and first_failure is None:
            first_failure = trace[-1]
    solved = first_failure is None
    if solved:
        feedback = "Your rule gives the right result in both situations."
    else:
        feedback = (f"When {first_failure['label']}, your rule makes the guardian {first_failure['action']}, "
                    f"but it should {first_failure['expected']}.")
    return {"solved": solved, "feedback": feedback, "trace": trace}


def _evaluate_loop(cfg: dict, program) -> dict:
    if not isinstance(program, (list, tuple)) or not program:
        raise PuzzleInputError("Add at least one instruction first.")
    if len(program) > cfg["max_slots"]:
        raise PuzzleInputError(f"The guardian's memory holds only {cfg['max_slots']} instructions.")
    steps = 0
    for item in program:
        if not isinstance(item, dict) or item.get("op") not in cfg["ops"]:
            raise PuzzleInputError("One of those instructions isn't available.")
        if item["op"] == "repeat":
            times = item.get("times")
            if not _is_int(times) or not 1 <= times <= cfg["max_repeat"]:
                raise PuzzleInputError(f"A repeat must run between 1 and {cfg['max_repeat']} times.")
            steps += times
        else:
            steps += 1

    length = cfg["length"]
    position, trace, bumped_at = 0, [0], None
    for i in range(1, steps + 1):
        if position + 1 > length:
            bumped_at = i
            break
        position += 1
        trace.append(position)
    solved = bumped_at is None and position == length
    if solved:
        feedback = f"The guardian takes {steps} steps and stops on tile {length}."
    elif bumped_at is not None:
        feedback = f"Step {bumped_at} would walk the guardian into the river, so it stopped on tile {position}."
    else:
        feedback = f"The guardian took {steps} step(s) and stopped on tile {position}. It needs to reach tile {length}."
    return {"solved": solved, "feedback": feedback, "trace": trace, "bumped_at": bumped_at, "steps": steps}


_EVALUATORS: dict = {
    "sequence": _evaluate_sequence,
    "conditional": _evaluate_conditional,
    "loop": _evaluate_loop,
}


def evaluate_puzzle(puzzle: dict, submission) -> dict:
    """Judge a submission. Returns {"solved", "feedback", "trace", ...}.

    Raises PuzzleInputError if the submission is malformed (that is not a wrong answer).
    """
    evaluator: Callable = _EVALUATORS.get(puzzle.get("kind"))
    if evaluator is None:
        raise StorageError(f"Unknown puzzle type '{puzzle.get('kind')}'.")
    return evaluator(puzzle["config"], submission)


# --------------------------------------------------------------------------- learning progress
def normalize_learning(learning) -> dict:
    """Return a complete, validated copy of a learning dict.

    Fills in fields that older saves lack. Raises StorageError for impossible data, for example a
    Python example that is 'unlocked' for a challenge that was never solved.
    """
    if not isinstance(learning, dict) or not isinstance(learning.get("concepts"), dict):
        raise StorageError("Save file has malformed learning data.")
    defaults = ConceptProgress().__dict__
    out = {"concepts": {}}
    for concept in CONCEPTS:
        raw = learning["concepts"].get(concept, {})
        if not isinstance(raw, dict):
            raise StorageError("Save file has malformed learning data.")
        progress = {key: raw.get(key, default) for key, default in defaults.items()}
        for key, default in defaults.items():
            ok = isinstance(progress[key], bool) if isinstance(default, bool) else (
                _is_int(progress[key]) and progress[key] >= 0)
            if not ok:
                raise StorageError(f"Save file has an invalid learning value for '{concept}'.")
        if progress["solved"] and progress["attempts"] < 1:
            raise StorageError(f"Learning data for '{concept}' says solved with no attempts.")
        if progress["python_unlocked"] and not progress["solved"]:
            raise StorageError(f"Learning data for '{concept}' unlocks Python without a solved challenge.")
        out["concepts"][concept] = progress
    return out


def record_attempt(learning: dict, concept: str, solved: bool) -> dict:
    """Return new learning data after one real attempt. Never un-solves a solved concept."""
    if concept not in CONCEPTS:
        raise ValueError(f"Unknown concept '{concept}'.")
    new = copy.deepcopy(learning)
    p = new["concepts"][concept]
    p["introduced"] = True
    p["attempts"] += 1
    if solved and not p["solved"]:
        p["solved"] = True
        p["python_unlocked"] = True
        p["attempts_to_solve"] = p["attempts"]
        p["hints_at_solve"] = p["hints_used"]
    return new


def record_hint(learning: dict, concept: str) -> dict:
    if concept not in CONCEPTS:
        raise ValueError(f"Unknown concept '{concept}'.")
    new = copy.deepcopy(learning)
    new["concepts"][concept]["hints_used"] += 1
    return new


def mark_introduced(learning: dict, concept: str) -> dict:
    if concept not in CONCEPTS:
        raise ValueError(f"Unknown concept '{concept}'.")
    new = copy.deepcopy(learning)
    new["concepts"][concept]["introduced"] = True
    return new


def understanding(progress: dict) -> str:
    """How the player did on this one challenge. A description of play, not of ability."""
    if not progress["solved"]:
        return "not_yet"
    if progress["hints_at_solve"] == 0 and progress["attempts_to_solve"] <= 2:
        return "independent"
    return "supported"


def next_recommendation(learning: dict) -> dict:
    """Which concept comes next, plus a supportive note. Based only on recorded outcomes."""
    concepts = learning["concepts"]
    nxt = next((c for c in CONCEPTS if not concepts[c]["solved"]), None)
    if nxt is None:
        return {"concept": None, "message": "You have solved all three mechanics."}
    if any(understanding(concepts[c]) == "supported" for c in CONCEPTS):
        message = "Take your time. Hints are always available, and using them is part of learning."
    else:
        message = "You're making steady progress."
    return {"concept": nxt, "message": message}
