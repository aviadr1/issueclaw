# Replay a frozen text briefing

The opt-in `briefing-replay.yml` reusable workflow runs the production single
writer, its normal helpers/advisor, and its bounded validator repairs against
an existing `daily-learning-briefing` artifact. It generates text only. It has
read-only GitHub permissions and accepts only model and private tracing secrets;
it has no collection, video, Slack, PR-comment or media-publication step.

Choose an evidence run from the caller repository, a resolved consumer config
and a file containing editorial instructions. The source must contain the
collection files listed in `briefing_replay.SOURCE_FILES`, the `pr-records/` and
`evidence/` directories, and the inventory messages named by `delivery.json`.
It also needs `briefing-config.json` or one unambiguous legacy
`config-<run>-<attempt>.json`. Repository/team/channel identity must match.
Prior reports, audits, lessons, videos and publication state are not copied.
Current editorial settings replace old modes, including Canvas/actions output.

For local use, with the repository's locked environment and Claude CLI installed:

```sh
uv run python -m issueclaw.briefing_replay \
  --source /path/to/downloaded-artifact --out /path/to/new-output \
  --config /path/to/consumer-config.json \
  --prompt src/issueclaw/prompts/daily-learning-briefing.md \
  --editorial /path/to/consumer-instructions.md
```

The output must be new and outside the source. There is no resume or alternate
writer mode. Local tracing follows the production environment configuration in
[the daily briefing guide](daily-learning-briefing.md). Set
`BRIEFING_REQUIRE_TRACE=1` to require a configured plugin before model execution.

For CI, call `aviadr1/issueclaw/.github/workflows/briefing-replay.yml@<commit-sha>`
from a manually dispatched caller job with `contents: read` and `actions: read`.
Pass these inputs:

| Input | Value |
| --- | --- |
| `evidence-run-id` | Completed source run ID in the caller repository |
| `evidence-artifact` | Defaults to `daily-learning-briefing` |
| `tooling-ref` | Exact 40-character issueclaw commit SHA containing this module |
| `claude-version` | Exact installed CLI release, in `x.y.z` form |
| `config` | Consumer JSON config path in the caller checkout |
| `editorial` | Consumer editorial instructions path in the caller checkout |
| `variant` | Descriptive instruction revision label, default `single-writer` |
| `langsmith-project` | Private project, default `briefing-replays` |
| `langsmith-workspace-id` | Workspace ID when required by the key |

Map `ANTHROPIC_API_KEY` and `LANGSMITH_API_KEY` explicitly. CI requires remote
trace verification; a session receipt alone is insufficient. Verification failure
fails the job even when generation validation passed. The pinned tracing plugin
uses redaction, and artifacts remain private. The model's ordinary tool access is
not a filesystem or network sandbox.

## Comparing results

`replay-metrics.json` separates the original `source_evidence_sha256` and source
file manifest from resolved config, editorial and prompt hashes. Changing editorial
instructions does not change the source evidence digest. `prepared_files` records
the effective inputs after applying configuration; the final check reads only
those files, including on generation failure. Deleted or modified inputs fail the
run. Unrelated transient tracing files do not participate in this check.

`replay-prompt.md` preserves the effective base prompt; generation request receipts
also capture the actual prompt with current actions-mode examples and repairs.
`briefing-replay-runtime.json` records actual tooling, consumer and tracing SHAs,
CLI/Node/Python versions, installed Python packages and the lockfile digest. Pin
the reusable workflow SHA as well as `tooling-ref` for comparisons. Hosted runner
images and server-side model behavior can still change between runs.

Metrics record generation/validation time and one final CLI cost result per call,
including helpers/advisor and failed attempts. Missing costs remain unknown with
a separate known subtotal. Do not add nested tracing token costs to CLI totals.
These are estimates, not invoices; CI setup, collection, video, runner and human
evaluation costs are outside generation timing/cost. Local runs should record
their runtime versions separately when comparing results.

The small `briefing-replay-results` artifact preserves metrics, the report, Slack
summary, runtime provenance and remote trace verification independently of the
full `briefing-replay` artifact. The latter contains evidence and transcripts but
excludes transient `langsmith_queue` files that can disappear during upload.

Compare reports blind to variant and cost. Check factual status, merge versus
rollout, prerequisites, waiting ownership, actual CI coverage, relevance, citations,
coverage and readability. Deterministic validation does not establish factual
completeness. Repeated quiet, busy and cross-repository snapshots are needed before
claiming a general quality gain. See the [historical results](briefing-experiment-results.md)
for the failed experiment that motivated this narrower tool.
