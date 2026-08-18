"""Config profiles: named bundles of run defaults you can switch between.

A profile captures the settings you would otherwise pass on every invocation:
the default agent, a pinned model (optional), the working directory, whether to
auto-approve danger tools, and extra environment variables (e.g. provider keys or
`ARCCODE_CONFIG`). One profile is "active" at a time; `run`/`chat` layer it under
explicit flags so the command line always wins.

Storage: ``$ARCCODE_HOME/profiles.json`` (default ``~/.arccode/profiles.json``)::

    {
      "active": "work",
      "profiles": {
        "work":  {"agent": "implementer", "yes": true,
                   "env": {"ARCCODE_CONFIG": "~/work/arccode.yaml"}},
        "local": {"model": "ollama/qwen2.5-3b", "agent": "researcher"}
      }
    }
"""
from __future__ import annotations

import json
import os
import pathlib
from dataclasses import asdict, dataclass, field

# Fields a profile may set. Kept explicit so we can validate and document them.
_FIELDS = ("agent", "model", "cwd", "yes", "max_steps", "env")


def _home() -> pathlib.Path:
    return pathlib.Path(os.environ.get("ARCCODE_HOME", pathlib.Path.home() / ".arccode"))


def _store_path() -> pathlib.Path:
    return _home() / "profiles.json"


@dataclass
class Profile:
    name: str
    agent: str | None = None
    model: str | None = None
    cwd: str | None = None
    yes: bool | None = None
    max_steps: int | None = None
    env: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {k: v for k, v in asdict(self).items() if k != "name" and v not in (None, {}, [])}
        return d

    @classmethod
    def from_dict(cls, name: str, data: dict) -> Profile:
        known = {k: data.get(k) for k in _FIELDS if k in data}
        env = known.pop("env", None) or {}
        if not isinstance(env, dict):
            env = {}
        return cls(name=name, env={str(k): str(v) for k, v in env.items()}, **known)


@dataclass
class ProfileStore:
    active: str | None = None
    profiles: dict[str, Profile] = field(default_factory=dict)

    # --- persistence -------------------------------------------------------
    @classmethod
    def load(cls) -> ProfileStore:
        path = _store_path()
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return cls()
        profs = {
            name: Profile.from_dict(name, pdata or {})
            for name, pdata in (data.get("profiles") or {}).items()
        }
        active = data.get("active")
        if active not in profs:
            active = None
        return cls(active=active, profiles=profs)

    def save(self) -> None:
        path = _store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "active": self.active,
            "profiles": {name: p.to_dict() for name, p in self.profiles.items()},
        }
        path.write_text(json.dumps(payload, indent=2))

    # --- mutations ---------------------------------------------------------
    def set(self, profile: Profile) -> None:
        self.profiles[profile.name] = profile
        if self.active is None:
            self.active = profile.name

    def delete(self, name: str) -> bool:
        if name not in self.profiles:
            return False
        del self.profiles[name]
        if self.active == name:
            self.active = None
        return True

    def use(self, name: str) -> bool:
        if name not in self.profiles:
            return False
        self.active = name
        return True

    def get(self, name: str) -> Profile | None:
        return self.profiles.get(name)

    def active_profile(self) -> Profile | None:
        return self.profiles.get(self.active) if self.active else None


def resolve_active() -> Profile | None:
    """The active profile, honoring an ARCCODE_PROFILE env override."""
    store = ProfileStore.load()
    override = os.environ.get("ARCCODE_PROFILE")
    if override:
        return store.get(override)
    return store.active_profile()


def apply_env(profile: Profile | None) -> list[str]:
    """Export a profile's env vars into the process (without clobbering ones the
    user already set explicitly). Returns the list of keys applied."""
    if not profile or not profile.env:
        return []
    applied = []
    for k, v in profile.env.items():
        if k not in os.environ:  # explicit environment wins
            os.environ[k] = os.path.expanduser(v) if "PATH" in k or "/" in v else v
            applied.append(k)
    return applied
