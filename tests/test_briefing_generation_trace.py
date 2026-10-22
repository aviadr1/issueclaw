import json
import io
from unittest.mock import patch

import pytest

from issueclaw import briefing_generation_trace as tracing


def test_costs_use_final_results_once_and_keep_missing_unknown(tmp_path):
    (tmp_path / "revision-1.tracing.log").write_text(
        "plugin diagnostic, not a model invocation"
    )
    (tmp_path / "generation.log").write_text(
        'not json\n{"type":"assistant","total_cost_usd":99}\n'
        '{"type":"result","total_cost_usd":1.25,"usage":{"output_tokens":10}}\n'
    )
    (tmp_path / "revision-2.log").write_text('{"type":"result","total_cost_usd":2.5}\n')
    assert tracing.cost_metrics(tmp_path)["reported_cost_usd"] == 3.75
    (tmp_path / "revision-1.log").write_text("interrupted\n")
    result = tracing.cost_metrics(tmp_path)
    assert result["reported_cost_usd"] is None
    assert result["known_cost_subtotal_usd"] == 3.75
    assert not result["cost_complete"]


def test_required_tracing_fails_before_model_without_key(tmp_path):
    with patch.dict(tracing.os.environ, {"BRIEFING_REQUIRE_TRACE": "1"}, clear=True):
        with pytest.raises(RuntimeError, match="Required"):
            tracing.claude_tracing(tmp_path, "ci")


def test_tracing_sessions_and_state_are_isolated_and_receipt_has_no_key(tmp_path):
    plugin = tmp_path / "plugin"
    (plugin / "bundle").mkdir(parents=True)
    (plugin / "bundle/dispatch.js").write_text("")
    env = {
        "CC_LANGSMITH_API_KEY": "secret-key",
        "LEARNING_TRACE_PLUGIN": str(plugin),
        "CC_LANGSMITH_PROJECT": "experiment",
        "BRIEFING_REPLAY_VARIANT": "instructions-v2",
    }
    with patch.dict(tracing.os.environ, env, clear=True):
        args1, env1 = tracing.claude_tracing(tmp_path / "ci", "ci")
        args2, env2 = tracing.claude_tracing(tmp_path / "learning", "learning")
    assert args1[-1] != args2[-1]
    assert env1["STATE_FILE"] != env2["STATE_FILE"]
    receipt = (tmp_path / "ci/ci.trace.json").read_text()
    assert "secret-key" not in receipt
    assert json.loads(receipt)["metadata"]["stage"] == "ci"


def test_verify_trace_queries_remote_after_plugin_clears_its_state(tmp_path):
    (tmp_path / "ci.trace.json").write_text(
        json.dumps({"session_id": "stable-session"})
    )
    (tmp_path / "ci.tracing-state.json").write_text(
        '{"stable-session": {"turn_count": 1}}'
    )
    observed = []

    def respond(request, **kwargs):
        observed.append(request)
        if request.full_url.endswith("/runs/query"):
            payload = json.loads(request.data)
            assert payload["is_root"] is True
            assert "stable-session" in payload["filter"]
            return io.StringIO(
                json.dumps(
                    {"runs": [{"id": "run1", "trace_id": "run1", "run_type": "chain"}]}
                )
            )
        return io.StringIO(json.dumps([{"id": "project1", "tenant_id": "workspace1"}]))

    with patch.dict(
        tracing.os.environ,
        {"CC_LANGSMITH_API_KEY": "secret", "CC_LANGSMITH_PROJECT": "experiment"},
        clear=True,
    ):
        with patch.object(tracing.urllib.request, "urlopen", side_effect=respond):
            tracing.verify_traces(tmp_path)
    rows = json.loads((tmp_path / "langsmith-traces.json").read_text())
    assert rows[0]["verified_remote"]
    assert rows[0]["url"].endswith("/t/stable-session")
    assert len(observed) == 2


@pytest.mark.parametrize("cost", [None, True, -1, float("nan"), float("inf"), "1.0"])
def test_invalid_cost_is_unknown_not_free(tmp_path, cost):
    (tmp_path / "generation.log").write_text(
        json.dumps({"type": "result", "total_cost_usd": cost}) + "\n"
    )
    metrics = tracing.cost_metrics(tmp_path)
    assert metrics["reported_cost_usd"] is None
    assert not metrics["cost_complete"]


def test_remote_verification_retries_project_lookup_and_records_failure(tmp_path):
    (tmp_path / "generation.trace.json").write_text('{"session_id":"one"}')
    with (
        patch.dict(
            tracing.os.environ,
            {
                "CC_LANGSMITH_API_KEY": "private-key",
                "CC_LANGSMITH_PROJECT": "briefing",
            },
        ),
        patch.object(
            tracing.urllib.request, "urlopen", side_effect=OSError("private-key")
        ) as request,
        patch.object(tracing.time, "sleep"),
    ):
        with pytest.raises(RuntimeError, match="could not be verified"):
            tracing.verify_traces(tmp_path)
    assert request.call_count == 4
    receipt = (tmp_path / "langsmith-traces.json").read_text()
    assert "private-key" not in receipt
    assert json.loads(receipt)[0]["verified_remote"] is False


def test_no_key_leaves_normal_generation_untraced(tmp_path):
    with patch.dict(tracing.os.environ, {}, clear=True):
        args, env = tracing.claude_tracing(tmp_path, "generation")
    assert args == []
    assert not list(tmp_path.iterdir())
