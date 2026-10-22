"""Load one shared defaults file and a team's explicit briefing overrides."""

import json
import re
from pathlib import Path


def _read_config(path: Path) -> dict:
    config = json.loads(path.read_text(encoding="utf-8"))
    videos = config.get("learning_videos")
    if isinstance(videos, dict) and "instructions_file" in videos:
        if "instructions" in videos:
            raise ValueError(
                f"{path}: use either learning_videos.instructions or instructions_file"
            )
        source = videos.pop("instructions_file")
        if not isinstance(source, str) or not source:
            raise ValueError(
                f"{path}: learning_videos.instructions_file must be a path"
            )
        # Resolve relative to the declaring file, before defaults/team merging.
        # Decode bytes directly to preserve all prompt whitespace, including CRLF.
        videos["instructions"] = (path.parent / source).read_bytes().decode("utf-8")
    return config


def load_config(path: Path) -> dict:
    config = _read_config(path)
    defaults_path = config.pop("defaults", None)
    if defaults_path is None:
        return config
    defaults = _read_config(path.parent / defaults_path)
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
        legacy = [
            candidate
            for candidate in out.glob("config-*-*.json")
            if re.fullmatch(r"config-\d+-\d+\.json", candidate.name)
        ]
        if not legacy:
            return config
        if len(legacy) != 1:
            raise ValueError("Prepared briefing has ambiguous legacy configurations")
        path = legacy[0]
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
