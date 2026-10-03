# MythCode

An adaptive fantasy world where every choice teaches you something.

**Status: Phase 2 (learning mechanics).** Playable with a prepared story and three puzzles. CrewAI/Gemini agents,
adaptive player modelling and AI-written scenes arrive in Phases 3-4. The full README is written in Phase 6.

## What you can play now
* The water crisis of Whispering Village, with three pathways (waterwheel, forest spirit, underground spring).
* Afterwards, a second quest in Mira's workshop: teach a clockwork guardian three ideas.
  1. **Sequence**: build a list of instructions; order matters.
  2. **Conditions**: build an IF / THEN / ELSE rule and test it against two situations.
  3. **Loops**: the guardian's memory holds two instructions, so you need a Repeat.
* Each puzzle has progressive hints. After a real solve, the matching Python example is revealed
  and kept in the **Unwritten Journal**.

Puzzles are judged by deterministic simulation in `core/learning_engine.py`. Nothing the player submits is ever
executed as code, and no AI decides whether an answer is right.

## Run locally
```
python -m venv .venv
.venv\Scripts\activate        # Windows (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
streamlit run app.py
```
Python version and deployment settings will be verified against current CrewAI and Streamlit documentation before Phase 3 (not yet confirmed).

## Secrets (optional until Phase 3)
Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill in your Gemini key. Never commit it.

## Tests
`pip install pytest` then `pytest`.

## Saving
Progress is saved by downloading a JSON file from the sidebar and uploading it later (Community Cloud has no
durable disk). There is no database in this build.

## Layout notes
`ui/puzzle_panels.py` holds the Streamlit panels for the puzzles; all game rules stay in `core/`.
