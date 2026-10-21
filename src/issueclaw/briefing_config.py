"""Load one shared defaults file and a team's explicit briefing overrides."""

import json
from pathlib import Path


def load_config(path: Path) -> dict:
    config = json.loads(path.read_text(encoding="utf-8"))
    defaults_path = config.pop("defaults", None)
    if defaults_path is None:
        return config
    defaults = json.loads((path.parent / defaults_path).read_text(encoding="utf-8"))
    if "defaults" in defaults:
        raise ValueError("Briefing defaults must be a standalone configuration")
    for key, value in config.items():
        if isinstance(value, dict) and isinstance(defaults.get(key), dict):
            defaults[key] = {**defaults[key], **value}
        else:
            defaults[key] = value
    return defaults


def prepared_config(config: dict, out: Path) -> dict:
    path = out / "briefing-config.json"
    if not path.exists():
        return config
    prepared = load_config(path)
    # Frozen evidence must never be reused for a different team or destination.
    if prepared.get("channel") != config.get("channel") or any(
        set(prepared.get(key, [])) != set(config.get(key, []))
        for key in ("repos", "teams")
    ):
        raise ValueError(
            "Prepared briefing belongs to different repositories, teams or channel"
        )
    return prepared
