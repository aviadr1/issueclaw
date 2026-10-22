"""Per-invocation tracing and CLI cost receipts for text briefing generation."""

import json
import math
import re
import os
import uuid
import time
import urllib.request
import urllib.parse
from pathlib import Path


def claude_tracing(directory: Path, name: str) -> tuple[list[str], dict]:
    env = dict(os.environ)
    plugin = env.get("LEARNING_TRACE_PLUGIN", "")
    enabled = bool(
        plugin
        and env.get("CC_LANGSMITH_API_KEY")
        and (Path(plugin) / "bundle/dispatch.js").is_file()
    )
    if not enabled:
        if env.get("BRIEFING_REQUIRE_TRACE") == "1":
            raise RuntimeError(
                "Required tracing needs the LangSmith key and tracing plugin"
            )
        return [], env
    directory.mkdir(parents=True, exist_ok=True)
    session = str(uuid.uuid4())
    metadata = {
        "workflow": "briefing-generation",
        "variant": env.get("BRIEFING_REPLAY_VARIANT", "production"),
        "stage": name,
        "ci_run": env.get("GITHUB_RUN_ID", ""),
        "ci_attempt": env.get("GITHUB_RUN_ATTEMPT", ""),
        "repository": env.get("GITHUB_REPOSITORY", ""),
        "commit_sha": env.get("GITHUB_SHA", ""),
        "evidence_run": env.get("BRIEFING_EVIDENCE_RUN", ""),
    }
    env.update(
        TRACE_TO_LANGSMITH="true",
        CC_LANGSMITH_REDACT="true",
        STATE_FILE=str((directory / f"{name}.tracing-state.json").resolve()),
        CC_LANGSMITH_LOG_FILE=str((directory / f"{name}.tracing.log").resolve()),
        CC_LANGSMITH_METADATA=json.dumps(metadata),
    )
    (directory / f"{name}.trace.json").write_text(
        json.dumps(
            {
                "session_id": session,
                "project": env.get("CC_LANGSMITH_PROJECT"),
                "metadata": metadata,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return ["--plugin-dir", str(Path(plugin).resolve()), "--session-id", session], env


def verify_traces(out: Path):
    """Confirm remote roots exist; a configured plugin alone is not upload proof."""
    endpoint = os.environ.get(
        "LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"
    ).rstrip("/")
    headers = {"x-api-key": os.environ["CC_LANGSMITH_API_KEY"]}
    if os.environ.get("LANGSMITH_WORKSPACE_ID"):
        headers["x-tenant-id"] = os.environ["LANGSMITH_WORKSPACE_ID"]

    def request_json(path, body=None):
        request = urllib.request.Request(
            endpoint + path,
            headers={**headers, "Content-Type": "application/json"},
            data=json.dumps(body).encode() if body is not None else None,
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)

    project = None
    receipts = sorted(out.glob("*.trace.json"))
    results = []
    for path in receipts:
        receipt = json.loads(path.read_text())
        if "session_id" not in receipt:
            continue
        row = {
            **receipt,
            "receipt": path.relative_to(out).as_posix(),
            "verified_remote": False,
        }
        for attempt in range(4):
            try:
                if not project:
                    projects = request_json(
                        "/sessions?"
                        + urllib.parse.urlencode(
                            {"name": os.environ["CC_LANGSMITH_PROJECT"]}
                        )
                    )
                    project = projects[0]
                if receipt.get("project") not in (
                    None,
                    os.environ["CC_LANGSMITH_PROJECT"],
                ):
                    raise RuntimeError("Trace belongs to another project")
                # SessionEnd clears transient plugin state. Query the stable
                # thread metadata, which the plugin puts on every remote run.
                query = {
                    "session": [project["id"]],
                    "filter": f'and(eq(metadata_key, "thread_id"), eq(metadata_value, {json.dumps(receipt["session_id"])}))',
                    "is_root": True,
                    "limit": 1,
                    "select": ["id", "trace_id", "run_type"],
                }
                remote = request_json("/runs/query", query)["runs"][0]
                root = remote["id"]
                row.update(
                    run_id=root,
                    verified_remote=True,
                    run_type=remote.get("run_type"),
                    trace_id=remote.get("trace_id"),
                )
                break
            except Exception:
                if attempt < 3:
                    time.sleep(2)
        if project:
            row["url"] = (
                f"https://smith.langchain.com/o/{project['tenant_id']}"
                f"/projects/p/{project['id']}/t/{receipt['session_id']}"
            )
        results.append(row)
    (out / "langsmith-traces.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )
    if not results or not all(row["verified_remote"] for row in results):
        raise RuntimeError(
            "Some LangSmith traces could not be verified; see langsmith-traces.json"
        )


def cost_metrics(out: Path) -> dict:
    """Use one final CLI result per invocation; never sum repeated usage events."""
    logs = sorted(out.glob("generation.log")) + sorted(
        path
        for path in out.glob("revision-*.log")
        if re.fullmatch(r"revision-\d+\.log", path.name)
    )
    invocations = []
    for path in logs:
        terminal = None
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("type") == "result":
                terminal = event
        invocations.append(
            {
                "log": path.relative_to(out).as_posix(),
                "has_terminal_result": terminal is not None,
                "reported_cost_usd": (terminal or {}).get("total_cost_usd"),
                "duration_ms": (terminal or {}).get("duration_ms"),
                "duration_api_ms": (terminal or {}).get("duration_api_ms"),
                "usage": (terminal or {}).get("usage"),
                "model_usage": (terminal or {}).get("modelUsage"),
                "session_id": (terminal or {}).get("session_id"),
                "is_error": (terminal or {}).get("is_error"),
            }
        )
    known = [
        row["reported_cost_usd"]
        for row in invocations
        if type(row["reported_cost_usd"]) in (int, float)
        and math.isfinite(row["reported_cost_usd"])
        and row["reported_cost_usd"] >= 0
    ]
    complete = bool(invocations) and len(known) == len(invocations)
    return {
        "invocations": invocations,
        "cost_complete": complete,
        "reported_cost_usd": sum(known) if complete else None,
        "known_cost_subtotal_usd": sum(known),
        "cost_basis": "Claude CLI final result per invocation, including CLI-managed subagents/advisor; not an invoice. Missing results are unknown, never zero.",
    }
