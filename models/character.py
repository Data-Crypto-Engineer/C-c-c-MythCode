from dataclasses import dataclass


@dataclass(frozen=True)
class Npc:
    id: str
    name: str
    role: str
    bio: str
