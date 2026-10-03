from dataclasses import dataclass, field


@dataclass(frozen=True)
class Quest:
    id: str
    title: str
    description: str
    pathways: list = field(default_factory=list)  # [{"id","title"}]
