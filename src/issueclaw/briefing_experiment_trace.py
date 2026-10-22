"""Optional, per-invocation LangSmith tracing for a briefing experiment."""

import json
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
                "Experiment requires the LangSmith key and tracing plugin"
            )
        return [], env
    directory.mkdir(parents=True, exist_ok=True)
    session = str(uuid.uuid4())
    metadata = {
        "experiment": "independent-briefing-writers",
        "arm": env.get("BRIEFING_EXPERIMENT_ARM", "baseline"),
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
    try:
        projects = request_json(
            "/sessions?"
            + urllib.parse.urlencode({"name": os.environ["CC_LANGSMITH_PROJECT"]})
        )
        if projects:
            project = projects[0]
    except Exception:
        pass  # Never put credential-bearing request details in artifacts.
    receipts = sorted(out.rglob("*.trace.json"))
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
                    raise RuntimeError("Tracing project lookup failed")
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
