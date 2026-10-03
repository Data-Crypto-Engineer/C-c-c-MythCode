# MythCode

An adaptive fantasy world where every choice teaches you something.

**Status: Phase 1 (foundation).** Playable with a prepared story; CrewAI/Gemini agents, puzzles and Python reveals come in later phases. Full README is written in Phase 6.

## Run locally
```
python -m venv .venv
.venv\Scripts\activate        # Windows (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
streamlit run app.py
```
Use Python 3.12 (Streamlit Community Cloud's default; the Python version is chosen in Advanced settings when deploying, not by a `runtime.txt`).

## Secrets (optional in Phase 1)
Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill in your Gemini key. Never commit it.

## Tests
`pip install pytest` then `pytest`.
