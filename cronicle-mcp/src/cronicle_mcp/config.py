"""Two-file config loader: hosts.json (URLs/timezone) + api_keys.json (secrets).

Resolution order for config dir:
  1. $CRONICLE_MCP_CONFIG_DIR if set
  2. <project_root>/.config/  where project_root is two parents above this file
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_DIR_ENV = "CRONICLE_MCP_CONFIG_DIR"


class ConfigError(RuntimeError):
    """Configuration is missing or invalid. Message is safe to surface to the user."""


@dataclass(frozen=True)
class HostConfig:
    name: str
    base_url: str
    api_key: str
    timezone: str = "Asia/Dhaka"
    request_timeout: int = 30
    rate_limit_delay_ms: int = 100
    # Friendly-name -> gmoXXX server-group ID. Manual because Cronicle Edge
    # does not expose get_server_groups. Empty dict if not set.
    groups: dict[str, str] = field(default_factory=dict)

    def __repr__(self) -> str:
        # Never include api_key in repr / logs / tracebacks.
        return (
            f"HostConfig(name={self.name!r}, base_url={self.base_url!r}, "
            f"api_key=<redacted>, timezone={self.timezone!r}, "
            f"groups={list(self.groups)})"
        )

    def resolve_group(self, name_or_id: str) -> str:
        """Return the gmo* id for a friendly name; pass through if already an id."""
        return self.groups.get(name_or_id, name_or_id)

    def group_name_for(self, group_id: str) -> str | None:
        """Reverse lookup: gmo* id -> friendly name, or None if unknown."""
        for name, gid in self.groups.items():
            if gid == group_id:
                return name
        return None


@dataclass(frozen=True)
class Config:
    hosts: dict[str, HostConfig]
    default_host: str

    def get(self, name: str | None) -> HostConfig:
        target = name or self.default_host
        if target not in self.hosts:
            raise ConfigError(
                f"Unknown host '{target}'. Configured: {sorted(self.hosts)}"
            )
        return self.hosts[target]


def config_dir() -> Path:
    override = os.environ.get(CONFIG_DIR_ENV)
    if override:
        return Path(override).expanduser().resolve()
    # config.py lives at <project>/src/cronicle_mcp/config.py
    return Path(__file__).resolve().parents[2] / ".config"


def load() -> Config:
    cdir = config_dir()
    hosts_path = cdir / "hosts.json"
    keys_path = cdir / "api_keys.json"

    if not hosts_path.exists():
        raise ConfigError(
            f"Missing {hosts_path}. Copy hosts.example.json to hosts.json and edit it."
        )
    if not keys_path.exists():
        raise ConfigError(
            f"Missing {keys_path}. Copy api_keys.example.json to api_keys.json and add your keys."
        )

    try:
        hosts_data = json.loads(hosts_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"{hosts_path}: invalid JSON ({e.msg} at line {e.lineno})") from None

    try:
        keys_data = json.loads(keys_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        # Don't echo file contents — could leak partial keys via traceback.
        raise ConfigError(f"api_keys.json: invalid JSON at line {e.lineno}") from None

    if not isinstance(hosts_data.get("hosts"), dict):
        raise ConfigError(f"{hosts_path}: 'hosts' must be an object")
    if not isinstance(keys_data, dict):
        raise ConfigError("api_keys.json: top-level must be an object {host: key}")

    default = hosts_data.get("default")
    if not default or not isinstance(default, str):
        raise ConfigError(f"{hosts_path}: 'default' (string) is required")

    hosts: dict[str, HostConfig] = {}
    for name, spec in hosts_data["hosts"].items():
        if not isinstance(spec, dict) or not spec.get("base_url"):
            raise ConfigError(f"Host '{name}': 'base_url' is required")
        key = keys_data.get(name)
        if not key or not isinstance(key, str) or key.startswith("REPLACE_"):
            raise ConfigError(
                f"No API key for host '{name}'. Edit {keys_path} and set the key."
            )
        groups_raw = spec.get("groups", {}) or {}
        if not isinstance(groups_raw, dict):
            raise ConfigError(f"Host '{name}': 'groups' must be an object")
        groups = {str(k): str(v) for k, v in groups_raw.items()}

        hosts[name] = HostConfig(
            name=name,
            base_url=spec["base_url"].rstrip("/"),
            api_key=key,
            timezone=spec.get("timezone", "Asia/Dhaka"),
            request_timeout=int(spec.get("request_timeout", 30)),
            rate_limit_delay_ms=int(spec.get("rate_limit_delay_ms", 100)),
            groups=groups,
        )

    if default not in hosts:
        raise ConfigError(
            f"default host '{default}' not in configured hosts: {sorted(hosts)}"
        )

    return Config(hosts=hosts, default_host=default)
