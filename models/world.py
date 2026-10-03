"""World state definition and the rules every saved world must obey."""
from dataclasses import dataclass, field

WATER_STATES = ("stopped", "damaged", "restored")  # may only move forward
GUARDIAN_STATES = ("inactive", "awakened", "guarding")
BOUNDED_FIELDS = {"forest_spirit_trust": (0, 100), "village_morale": (0, 100)}


@dataclass
class WorldState:
    kingdom: str = "Elarion"
    current_location: str = "whispering_village"
    water_supply: str = "stopped"
    forest_spirit_trust: int = 20
    clockwork_guardian: str = "inactive"
    village_morale: int = 60
    active_quest: str = "water_crisis"
    completed_quests: list = field(default_factory=list)
    discovered_locations: list = field(default_factory=lambda: ["whispering_village"])
    important_choices: list = field(default_factory=list)
    character_memories: dict = field(default_factory=dict)  # {npc_id: {tag: text}}
