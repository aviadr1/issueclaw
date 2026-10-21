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


def test_defaults_are_one_file_not_an_inheritance_chain(tmp_path):
    (tmp_path / "defaults.json").write_text('{"defaults": "config.json"}')
    config = tmp_path / "config.json"
    config.write_text('{"defaults": "defaults.json"}')
    with pytest.raises(ValueError, match="standalone"):
        briefing_config.load_config(config)


def test_prepared_report_retains_options_when_shared_defaults_change(tmp_path):
    defaults = tmp_path / "defaults.json"
    defaults.write_text('{"learning_videos": {"max": 1}}')
    team = tmp_path / "frontend.json"
    team.write_text(
        '{"defaults": "defaults.json", "repos": ["org/web"], "channel": "C123"}'
    )
    original = briefing_config.load_config(team)
    (tmp_path / "briefing-config.json").write_text(json.dumps(original))
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
def test_other_teams_cannot_reuse_prepared_evidence(tmp_path, override):
    config = {"repos": ["org/web"], "teams": ["WEB"], "channel": "C123"}
    (tmp_path / "briefing-config.json").write_text(json.dumps(config))
    with pytest.raises(ValueError, match="different repositories, teams or channel"):
        briefing_config.prepared_config({**config, **override}, tmp_path)


def test_legacy_artifacts_without_a_snapshot_remain_recoverable(tmp_path):
    config = {"repos": ["org/repo"], "channel": "C123"}
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
