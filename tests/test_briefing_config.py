import json

import pytest

from issueclaw import briefing_config


def test_team_overrides_keep_other_defaults_and_replace_lists(tmp_path, monkeypatch):
    defaults = {
        "timezone": "UTC",
        "repos": ["org/backend"],
        "people": {"alice": "Alice", "bob": "Robert"},
        "learning_videos": {"max": 1, "review": True, "quality_checks": True},
    }
    (tmp_path / "defaults.json").write_text(json.dumps(defaults))
    team = tmp_path / "frontend.json"
    team.write_text(
        json.dumps(
            {
                "defaults": "defaults.json",
                "repos": ["org/web", "org/mobile"],
                "people": {"bob": "Bob"},
                "learning_videos": {"review": False},
                "context_terms": [],
            }
        )
    )
    monkeypatch.chdir(tmp_path.parent)
    resolved = briefing_config.load_config(team)
    assert resolved == {
        "timezone": "UTC",
        "repos": ["org/web", "org/mobile"],
        "people": {"alice": "Alice", "bob": "Bob"},
        "learning_videos": {"max": 1, "review": False, "quality_checks": True},
        "context_terms": [],
    }
    assert json.loads((tmp_path / "defaults.json").read_text()) == defaults


def test_standalone_config_needs_no_defaults_file(tmp_path):
    path = tmp_path / "config.json"
    config = {"repos": ["org/repo"], "channel": "C123"}
    path.write_text(json.dumps(config))
    assert briefing_config.load_config(path) == config


def test_instructions_file_preserves_text_and_freezes_it_for_recovery(tmp_path):
    text = "First line.\r\nSecond line.\n\nUnicode: café.  "
    prompt = tmp_path / "lesson.md"
    prompt.write_bytes(text.encode("utf-8"))
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "channel": "C123",
                "learning_videos": {"instructions_file": "lesson.md", "max": 1},
            }
        )
    )
    resolved = briefing_config.load_config(path)
    assert resolved["learning_videos"] == {"instructions": text, "max": 1}
    (tmp_path / "briefing-config.json").write_text(json.dumps(resolved))
    prompt.unlink()
    assert briefing_config.prepared_config({"channel": "C123"}, tmp_path) == resolved


@pytest.mark.parametrize("override", ["none", "inline", "file"])
def test_instructions_resolve_from_the_declaring_config(
    tmp_path, monkeypatch, override
):
    shared = tmp_path / "shared"
    team = tmp_path / "team"
    shared.mkdir()
    team.mkdir()
    (shared / "lesson.md").write_text("Shared guidance", encoding="utf-8")
    (team / "lesson.md").write_text("Team guidance", encoding="utf-8")
    (shared / "defaults.json").write_text(
        json.dumps({"learning_videos": {"instructions_file": "lesson.md", "max": 1}})
    )
    videos: dict = {"review": True}
    if override == "inline":
        videos["instructions"] = "Inline guidance"
    elif override == "file":
        videos["instructions_file"] = "lesson.md"
    path = team / "config.json"
    path.write_text(
        json.dumps({"defaults": "../shared/defaults.json", "learning_videos": videos})
    )
    monkeypatch.chdir(tmp_path.parent)
    assert briefing_config.load_config(path)["learning_videos"] == {
        "instructions": {
            "none": "Shared guidance",
            "inline": "Inline guidance",
            "file": "Team guidance",
        }[override],
        "max": 1,
        "review": True,
    }


def test_instructions_file_overrides_inline_defaults(tmp_path):
    (tmp_path / "defaults.json").write_text(
        '{"learning_videos": {"instructions": "Shared guidance"}}'
    )
    (tmp_path / "lesson.md").write_text("Team guidance", encoding="utf-8")
    path = tmp_path / "config.json"
    path.write_text(
        '{"defaults": "defaults.json", '
        '"learning_videos": {"instructions_file": "lesson.md"}}'
    )
    assert briefing_config.load_config(path)["learning_videos"] == {
        "instructions": "Team guidance"
    }


@pytest.mark.parametrize("source", [None, 7, ""])
def test_instructions_file_requires_a_path(tmp_path, source):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"learning_videos": {"instructions_file": source}}))
    with pytest.raises(ValueError, match="instructions_file must be a path"):
        briefing_config.load_config(path)


def test_instructions_file_does_not_silently_ignore_conflicts_or_missing_files(
    tmp_path,
):
    path = tmp_path / "config.json"
    path.write_text(
        '{"learning_videos": {"instructions": "Inline", "instructions_file": "absent.md"}}'
    )
    with pytest.raises(ValueError, match="use either"):
        briefing_config.load_config(path)
    path.write_text('{"learning_videos": {"instructions_file": "absent.md"}}')
    with pytest.raises(FileNotFoundError, match="absent.md"):
        briefing_config.load_config(path)


def test_defaults_are_one_file_not_an_inheritance_chain(tmp_path):
    (tmp_path / "defaults.json").write_text('{"defaults": "config.json"}')
    config = tmp_path / "config.json"
    config.write_text('{"defaults": "defaults.json"}')
    with pytest.raises(ValueError, match="standalone"):
        briefing_config.load_config(config)


@pytest.mark.parametrize("manifest", ["briefing-config.json", "config-123-1.json"])
def test_prepared_report_retains_options_when_shared_defaults_change(
    tmp_path, manifest
):
    defaults = tmp_path / "defaults.json"
    defaults.write_text('{"learning_videos": {"max": 1}}')
    team = tmp_path / "frontend.json"
    team.write_text(
        '{"defaults": "defaults.json", "repos": ["org/web"], "channel": "C123"}'
    )
    original = briefing_config.load_config(team)
    (tmp_path / manifest).write_text(json.dumps(original))
    defaults.write_text('{"learning_videos": {"max": 2}}')
    current = briefing_config.load_config(team)
    assert current["learning_videos"]["max"] == 2
    assert briefing_config.prepared_config(current, tmp_path) == original


@pytest.mark.parametrize(
    "override",
    [
        {"repos": ["org/backend"]},
        {"teams": ["BE"]},
        {"channel": "C456"},
    ],
)
@pytest.mark.parametrize("manifest", ["briefing-config.json", "config-123-1.json"])
def test_other_teams_cannot_reuse_prepared_evidence(tmp_path, override, manifest):
    config = {"repos": ["org/web"], "teams": ["WEB"], "channel": "C123"}
    (tmp_path / manifest).write_text(json.dumps(config))
    with pytest.raises(ValueError, match="different repositories, teams or channel"):
        briefing_config.prepared_config({**config, **override}, tmp_path)


def test_legacy_artifacts_without_a_snapshot_remain_recoverable(tmp_path):
    config = {"repos": ["org/repo"], "channel": "C123"}
    assert briefing_config.prepared_config(config, tmp_path) == config


def test_ambiguous_legacy_configs_are_not_guessed(tmp_path):
    config = {"repos": ["org/repo"], "channel": "C123"}
    for attempt in (1, 2):
        (tmp_path / f"config-123-{attempt}.json").write_text(json.dumps(config))
    with pytest.raises(ValueError, match="ambiguous legacy"):
        briefing_config.prepared_config(config, tmp_path)
    (tmp_path / "briefing-config.json").write_text(json.dumps(config))
    assert briefing_config.prepared_config(config, tmp_path) == config


def test_unrelated_config_filenames_are_not_treated_as_snapshots(tmp_path):
    (tmp_path / "config-team-defaults.json").write_text("not a snapshot")
    config = {"channel": "C123"}
    assert briefing_config.prepared_config(config, tmp_path) == config


def test_reordering_sources_does_not_prevent_recovery(tmp_path):
    config = {
        "repos": ["org/web", "org/mobile"],
        "teams": ["WEB", "MOB"],
        "channel": "C123",
    }
    (tmp_path / "briefing-config.json").write_text(json.dumps(config))
    assert (
        briefing_config.prepared_config(
            {**config, "repos": ["org/mobile", "org/web"], "teams": ["MOB", "WEB"]},
            tmp_path,
        )
        == config
    )
