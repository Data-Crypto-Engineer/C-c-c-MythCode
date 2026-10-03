"""Validation of player-entered text."""
import re

from models.player import ROLES, STYLES
from utils.error_handler import MythCodeError

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 '\-]{0,23}$")


class InputError(MythCodeError):
    pass


def clean_player_name(raw: str) -> str:
    name = " ".join((raw or "").split())
    if not _NAME_RE.match(name):
        raise InputError("Please enter a name of 1-24 letters, numbers, spaces, apostrophes or hyphens.")
    return name


def clean_choice(value: str, allowed: tuple, label: str) -> str:
    if value not in allowed:
        raise InputError(f"Please pick a valid {label}.")
    return value


def validate_character(name: str, role: str, style: str):
    return clean_player_name(name), clean_choice(role, ROLES, "role"), clean_choice(style, STYLES, "adventure style")
