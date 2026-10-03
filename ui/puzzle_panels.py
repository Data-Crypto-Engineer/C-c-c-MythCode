"""Streamlit panels for the three puzzles, hints and the Python reveal.

The UI only collects a submission (a list of buttons pressed, or a chosen rule) and hands it to
core.game_engine.submit_puzzle(); correctness is always decided there, never here.
The player's in-progress program lives in st.session_state["puzzle_work"] (temporary UI state);
attempts, hints and progress live in the saved game state.
"""
import streamlit as st

from core.game_engine import request_hint, submit_puzzle

ARROWS = {"east": "▶", "south": "▼", "west": "◀", "north": "▲"}
SEQ_LABELS = {"forward": "⬆ Forward", "turn_right": "↪ Turn right", "turn_left": "↩ Turn left"}


# ------------------------------------------------------------------ shared helpers
def _work(scene_id: str) -> dict:
    """The player's unsubmitted work for this scene (reset automatically when the scene changes)."""
    work = st.session_state.get("puzzle_work")
    if not work or work["scene"] != scene_id:
        work = {"scene": scene_id, "program": [], "result": None}
        st.session_state["puzzle_work"] = work
    return work


def _edit(work: dict, program: list) -> None:
    work["program"] = program
    work["result"] = None
    st.rerun()


def _program_controls(work: dict, key: str) -> bool:
    """Undo / Clear / Run buttons. Returns True when Run was pressed."""
    undo, clear, run = st.columns(3)
    if undo.button("⌫ Undo", key=f"{key}_undo", disabled=not work["program"]):
        _edit(work, work["program"][:-1])
    if clear.button("Clear", key=f"{key}_clear", disabled=not work["program"]):
        _edit(work, [])
    return run.button("▶ Run", key=f"{key}_run", type="primary", disabled=not work["program"])


def render_reveal(reveal: dict, compact: bool = False) -> None:
    """Show a revealed Python example. Callers must only pass reveals the player has unlocked."""
    def body():
        st.code(reveal["python"], language="python")
        st.write(reveal["explanation"])

    if compact:
        with st.expander(f"Python unlocked: {reveal['name']}"):
            body()
    else:
        st.success(f"You've just used a real programming idea: **{reveal['name']}**")
        body()


# ------------------------------------------------------------------ sequence
def _board_text(cfg: dict, trace) -> str:
    walls = {(w["x"], w["y"]) for w in cfg["walls"]}
    goal = (cfg["goal"]["x"], cfg["goal"]["y"])
    trail = {(t["x"], t["y"]) for t in trace} if trace else set()
    here = trace[-1] if trace else cfg["start"]
    rows = []
    for y in range(cfg["height"]):
        cells = []
        for x in range(cfg["width"]):
            if (x, y) == (here["x"], here["y"]):
                cells.append(ARROWS[here["facing"]])
            elif (x, y) in walls:
                cells.append("▓")
            elif (x, y) == goal:
                cells.append("★")
            elif (x, y) in trail:
                cells.append("○")
            else:
                cells.append("·")
        rows.append(" ".join(cells))
    return "\n".join(rows)


def _sequence_panel(p: dict, work: dict):
    cfg, result = p["config"], work["result"]
    st.code(_board_text(cfg, result["trace"] if result else None), language="text")
    st.caption("▶▼◀▲ guardian   ★ pedestal   ▓ stone block   ○ where it has walked")
    full = len(work["program"]) >= cfg["max_instructions"]
    for col, action in zip(st.columns(len(cfg["actions"])), cfg["actions"]):
        if col.button(SEQ_LABELS[action], key=f"seq_{action}", disabled=full):
            _edit(work, work["program"] + [action])
    steps = " → ".join(f"{i}. {SEQ_LABELS[a]}" for i, a in enumerate(work["program"], 1))
    st.markdown(steps or "*No instructions yet.*")
    st.caption(f"{len(work['program'])}/{cfg['max_instructions']} instructions")
    return list(work["program"]) if _program_controls(work, "seq") else None


# ------------------------------------------------------------------ conditions
def _conditions_panel(p: dict, work: dict):
    cfg = p["config"]
    cond_labels = {c["id"]: c["label"] for c in cfg["conditions"]}
    act_labels = {a["id"]: a["label"] for a in cfg["actions"]}

    def fmt(labels):
        return lambda i: "— choose —" if i == "" else labels[i]

    cond = st.selectbox("IF", [""] + list(cond_labels), format_func=fmt(cond_labels), key="rule_if")
    then = st.selectbox("THEN the guardian will", [""] + list(act_labels), format_func=fmt(act_labels), key="rule_then")
    other = st.selectbox("ELSE the guardian will", [""] + list(act_labels), format_func=fmt(act_labels), key="rule_else")
    if cond and then and other:
        st.markdown(f"**Your rule:** IF {cond_labels[cond]}, THEN {act_labels[then]}, ELSE {act_labels[other]}.")
    if st.button("🧪 Test my rule", key="rule_test", type="primary"):
        return {"condition": cond, "then": then, "else": other}
    return None


# ------------------------------------------------------------------ loops
def _loop_text(item: dict) -> str:
    return "Move forward" if item["op"] == "forward" else f"Repeat {item['times']} × Move forward"


def _loop_panel(p: dict, work: dict):
    cfg, result = p["config"], work["result"]
    length = cfg["length"]
    here = result["trace"][-1] if result and result["trace"] else 0
    head = ["start".center(7)] + [(f"{k}★" if k == length else str(k)).center(7) for k in range(1, length + 1)]
    body = [f"[ {'G' if k == here else '·'} ]".center(7) for k in range(length + 1)]
    st.code("".join(head) + "\n" + "".join(body), language="text")
    st.caption(f"G = guardian   ★ = the tile it must stop on   Beyond tile {length} is the river.")
    full = len(work["program"]) >= cfg["max_slots"]
    add_fwd, times_col, add_rep = st.columns([2, 1, 2])
    if add_fwd.button("➕ Move forward", key="loop_fwd", disabled=full):
        _edit(work, work["program"] + [{"op": "forward"}])
    times = times_col.selectbox("Times", list(range(2, cfg["max_repeat"] + 1)), index=1, key="loop_times",
                                label_visibility="collapsed")
    if add_rep.button(f"➕ Repeat {times} × forward", key="loop_rep", disabled=full):
        _edit(work, work["program"] + [{"op": "repeat", "times": times}])
    lines = [f"{i}. {_loop_text(item)}" for i, item in enumerate(work["program"], 1)]
    st.markdown("  \n".join(lines) or "*No instructions yet.*")
    st.caption(f"Guardian's memory: {len(work['program'])}/{cfg['max_slots']} instructions")
    return list(work["program"]) if _program_controls(work, "loop") else None


# ------------------------------------------------------------------ results, hints, entry point
def _show_result(p: dict, work: dict) -> None:
    result = work["result"]
    if not result:
        return
    if result["valid"]:
        st.warning(f"Not quite. {result['feedback']}")
    else:
        st.warning(result["feedback"])
    if p["kind"] == "conditional" and result["trace"]:
        for t in result["trace"]:
            mark = "✅" if t["ok"] else "❌"
            extra = "" if t["ok"] else f" (it should {t['expected']})"
            st.markdown(f"{mark} When {t['label']}, the guardian will **{t['action']}**{extra}.")


def _hints(game: dict, p: dict, content) -> None:
    for i, hint in enumerate(p["hints_shown"], 1):
        st.info(f"💡 Hint {i}: {hint}")
    left = p["hints_total"] - len(p["hints_shown"])
    if left and st.button(f"💡 I'd like a hint ({left} left)", key=f"hint_{p['id']}"):
        st.session_state.game, _hint = request_hint(game, content)
        st.rerun()


_PANELS = {"sequence": _sequence_panel, "conditional": _conditions_panel, "loop": _loop_panel}


def render_puzzle(game: dict, view: dict, content) -> None:
    p = view["puzzle"]
    work = _work(game["scene_id"])
    st.subheader(f"🧩 {p['title']}")
    st.write(p["instructions"])
    submission = _PANELS[p["kind"]](p, work)
    if submission is not None:
        new_game, result = submit_puzzle(game, submission, content)
        st.session_state.game = new_game
        if result["solved"]:
            st.session_state.flash = content.puzzles[p["id"]]["success"]
            st.session_state.puzzle_work = None
        else:
            work["result"] = result
        st.rerun()
    _show_result(p, work)
    _hints(game, p, content)
