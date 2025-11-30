import tomllib
from dataclasses import dataclass
from typing import Self

@dataclass(frozen=True)
class Config:
    EVENT_API: str
    POLL_INTERVAL: int
    GH_TOKEN: str
    DISCORD_WEBHOOK: str
    REPO_BLACKLIST: list[str]
    EVENT_BLACKLIST: list[str]
    USER_WHITELIST: list[str]

    @classmethod
    def from_toml(cls, path: str) -> Self:
        with open(path, 'rb') as f:
            data = tomllib.load(f)
        return cls(**data)

