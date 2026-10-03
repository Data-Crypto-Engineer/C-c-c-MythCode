"""Helpers that turn Python data into plain prompt text.

CrewAI treats {curly_braces} in task text as placeholders, so prompt text built
here never contains curly braces: they are swapped for round brackets.
"""
from __future__ import annotations

from typing import Any, Mapping


def plain(value: Any, max_len: int = 300) -> str:
    text = str(value).replace("{", "(").replace("}", ")").replace("\n", " ").strip()
    return text[:max_len]


def render_context(data: Mapping[str, Any], max_items: int = 12) -> str:
    """Flatten nested data into '- path: value' lines without braces."""
    lines: list[str] = []

    def walk(path: str, value: Any) -> None:
        if isinstance(value, Mapping):
            for key, inner in value.items():
                walk(f"{path}.{key}" if path else str(key), inner)
        elif isinstance(value, (list, tuple, set)):
            items = [plain(v, 100) for v in list(value)[:max_items]]
            lines.append(f"- {plain(path, 60)}: " + ("; ".join(items) if items else "(none)"))
        else:
            lines.append(f"- {plain(path, 60)}: {plain(value)}")

    walk("", data)
    return "\n".join(lines)
