"""MythCode - Streamlit front end (Phase 2: prepared story + three playable puzzles, no AI calls yet)."""
import streamlit as st

from core.game_engine import apply_choice, get_scene_view
from core.quest_manager import load_content, quest_summary
from core.state_manager import new_game_state, state_from_json, state_to_json
from core.game_engine import reveal_for
from core.learning_engine import UNDERSTANDING_LABELS, next_recommendation, understanding
from models.learning import CONCEPT_LABELS, CONCEPTS
from models.player import ROLES, STYLES
from models.world import WATER_STATES
from utils.config import llm_status
from utils.error_handler import MythCodeError, user_message
from utils.logger import get_logger
from utils.validators import InputError, validate_character
from ui.puzzle_panels import render_puzzle, render_reveal

log = get_logger()
TAGLINE = "An adaptive fantasy world where every choice teaches you something."

st.set_page_config(page_title="MythCode", page_icon="🔮", layout="centered")

st.markdown(
    """
<style>
.stApp { background: linear-gradient(180deg, #f6f1e7 0%, #eae6f3 100%); }
h1, h2, h3, .scene-text { font-family: Georgia, 'Times New Roman', serif; color: #3b3a4f; }
.scene-text { font-size: 1.1rem; line-height: 1.7; color: #3f3a36; }
.dialogue { border-left: 4px solid #c9a24d; background: #fbf7ec; padding: .6rem 1rem; margin: .6rem 0;
            border-radius: 0 10px 10px 0; font-family: Georgia, serif; color: #3f3a36; }
.dialogue b { color: #4f6b4a; }
div.stButton > button { border-radius: 12px; border: 1px solid #b9b2d6; background: #f4f1fb; color: #3b3a4f; }
div.stButton > button:hover { border-color: #c9a24d; background: #fbf4df; color: #3b3a4f; }
</style>
""",
    unsafe_allow_html=True,
)

try:
    content = load_content()
except MythCodeError as exc:
    st.error(user_message(exc))
    st.stop()
ss = st.session_state
ss.setdefault("screen", "welcome")
ss.setdefault("game", None)
ss.setdefault("flash", None)


def go(screen: str):
    ss.screen = screen


def reset_game():
    ss.game = None
    ss.flash = None
    go("welcome")


# ---------------------------------------------------------------- welcome
def show_welcome():
    st.title("🔮 MythCode")
    st.subheader(TAGLINE)
    st.write(
        "The well of Whispering Village has run dry. Talk to its people, make choices that matter, "
        "and along the way discover how rules, conditions and repetition shape a world. "
        "The Python hiding inside the magic is revealed as you play."
    )
    if st.button("Start Adventure", type="primary"):
        go("create")
        st.rerun()
    st.divider()
    st.caption("Continue a saved adventure")
    uploaded = st.file_uploader("Upload your MythCode save file (.json)", type=["json"])
    if uploaded is not None and st.button("Continue Adventure"):
        try:
            ss.game = state_from_json(uploaded.getvalue().decode("utf-8", errors="replace"), content)
            go("play")
            st.rerun()
        except MythCodeError as exc:
            log.warning("Load failed: %s", exc)
            st.error(user_message(exc))


# ---------------------------------------------------------------- creation
def show_create():
    st.header("Create your character")
    name = st.text_input("Character name", max_chars=24)
    role = st.selectbox("Fantasy role", ROLES, help="A flavour choice only; it doesn't limit what you can do.")
    style = st.selectbox("Preferred adventure style (optional)", STYLES)
    left, right = st.columns(2)
    if left.button("Enter Elarion", type="primary"):
        try:
            validate_character(name, role, style)
            ss.game = new_game_state(name, role, style, content)
            go("play")
            st.rerun()
        except InputError as exc:
            st.error(str(exc))
    if right.button("Back"):
        go("welcome")
        st.rerun()


# ---------------------------------------------------------------- play
def show_sidebar(game: dict):
    with st.sidebar:
        st.markdown(f"### {game['player']['name']}")
        st.caption(f"{game['player']['role']} · turn {game['turn']}")
        st.download_button("💾 Download save file", state_to_json(game),
                           file_name="mythcode_save.json", mime="application/json")
        st.caption("Saves live on your device. This app does not store progress online.")
        ok, msg = llm_status()
        st.caption("AI storyteller: ready" if ok else "AI storyteller: not set up. Using the prepared story.")
        if msg and not ok:
            st.caption(msg)
        with st.expander("New game / reset"):
            st.warning("This deletes your current progress. Download a save first if you want to keep it.")
            confirm = st.checkbox("Yes, delete my current adventure")
            if st.button("Reset adventure", disabled=not confirm):
                reset_game()
                st.rerun()


def tab_adventure(game: dict):
    view = get_scene_view(game, content)
    st.caption(f"📍 {view['location']}")
    st.header(view["title"])
    st.write(view["text"])
    for speaker, line in view["dialogue"]:
        st.markdown(f"<div class='dialogue'><b>{speaker}:</b> “{line}”</div>", unsafe_allow_html=True)
    if ss.flash:
        st.info(ss.flash)
        ss.flash = None
    if view["reveal"]:
        render_reveal(view["reveal"])
    if view["puzzle"]:
        render_puzzle(game, view, content)
        return
    if view["is_end"]:
        st.success("You have finished this chapter of MythCode. The AI storyteller and a world that adapts to how you play arrive in later build phases.")
        if st.button("Begin a new adventure"):
            reset_game()
            st.rerun()
        return
    st.markdown("**What do you do?**")
    for choice_id, label in view["choices"]:
        if st.button(label, key=f"{game['scene_id']}:{choice_id}"):
            ss.game, ss.flash = apply_choice(game, choice_id, content)
            st.rerun()


def tab_quests(game: dict):
    q = quest_summary(game["world"], content)
    st.header("Quest Journal")
    if q["current"]:
        st.subheader(q["current"].title)
        st.write(q["current"].description)
    st.markdown("**Completed missions**")
    st.write("\n".join(f"- {t}" for t in q["completed"]) or "None yet.")
    st.markdown("**Important choices**")
    st.write("\n".join(f"- {t}" for t in q["choices"]) or "None yet.")
    st.markdown("**Discoveries**")
    st.write("\n".join(f"- {t}" for t in q["discoveries"]))
    st.markdown("**Unresolved**")
    st.write("\n".join(f"- {t}" for t in q["unresolved"]) or "Nothing outstanding.")


def tab_learning(game: dict):
    st.header("The Unwritten Journal")
    st.caption("Concepts appear here once you meet them in play. A Python example unlocks after you solve its challenge.")
    learning = game["learning"]
    solved = sum(learning["concepts"][c]["solved"] for c in CONCEPTS)
    st.progress(solved / len(CONCEPTS))
    st.caption(f"{solved} of {len(CONCEPTS)} mechanics solved")
    for concept in CONCEPTS:
        p = learning["concepts"][concept]
        label = CONCEPT_LABELS[concept]
        if not p["introduced"]:
            st.markdown(f"**{label}** · not yet encountered")
            continue
        state = "Solved" if p["solved"] else "In progress"
        st.markdown(f"**{label}** · {state} · attempts: {p['attempts']} · hints used: {p['hints_used']}")
        if p["solved"]:
            st.caption(UNDERSTANDING_LABELS[understanding(p)] + " (this challenge only).")
        if p["python_unlocked"]:
            render_reveal(reveal_for(concept, content), compact=True)
    st.info(next_recommendation(learning)["message"])


def tab_world(game: dict):
    w = game["world"]
    st.header("World Status")
    st.write(f"**Kingdom:** {w['kingdom']}")
    st.write(f"**Village water:** {w['water_supply'].title()}")
    st.progress(WATER_STATES.index(w["water_supply"]) / (len(WATER_STATES) - 1))
    st.write(f"**Village morale:** {w['village_morale']}/100")
    st.progress(w["village_morale"] / 100)
    st.write(f"**Forest spirit trust:** {w['forest_spirit_trust']}/100")
    st.progress(w["forest_spirit_trust"] / 100)
    st.write(f"**Clockwork guardian:** {w['clockwork_guardian'].title()}")


def show_play():
    game = ss.game
    if not game:
        go("welcome")
        st.rerun()
        return
    show_sidebar(game)
    t1, t2, t3, t4 = st.tabs(["Adventure", "Quest Journal", "Learning Journal", "World Status"])
    with t1:
        tab_adventure(game)
    with t2:
        tab_quests(game)
    with t3:
        tab_learning(game)
    with t4:
        tab_world(game)


{"welcome": show_welcome, "create": show_create, "play": show_play}.get(ss.screen, show_welcome)()
