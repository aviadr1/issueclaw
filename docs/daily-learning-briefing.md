# Daily learning briefings

A knowledge repository can run the reusable `daily-learning-briefing.yml` workflow
with its own source configuration, schedule and existing reporting secrets. The
workflow collects GitHub/Linear-mirror evidence, generates one concrete brief with
named authors and reviewers, validates coverage, validates per-PR coverage and review-learning JSON audits, preserves artifacts, and posts a
channel message plus the complete inventory as replies, or one TLDR linking to a full Slack Canvas.

## Caller configuration

The JSON config supplies `repos` (owner/repo names), `people` (verified login/name
mapping, matched case-insensitively), `teams` (relevant Linear team identifiers), `timezone` (IANA), `hour`,
`weekdays` (optional Python weekday numbers, Monday=0; all days by default),
`channel` (Slack channel ID), `mirror_repository`, and `state_branch`. Set
`delivery_format: "canvas"` for a full report plus complete PR/ticket inventory in
a channel-tabbed Canvas and one short TLDR message. Legacy thread delivery remains
the default. The full Canvas report has no 550-word limit; only the TLDR is capped
at 180 words. Keep company
configuration in the caller. Pin both the reusable workflow and `tooling-ref` to
the same reviewed issueclaw commit. Required secrets are `REPOS_READ_TOKEN`,
`ANTHROPIC_API_KEY`, and `SLACK_BOT_TOKEN`. The caller's `GITHUB_TOKEN` needs
`contents: write` and `actions: read` for checkpoints and recovery artifacts.
The existing Slack bot needs membership and posting permission in the destination.
Canvas delivery also needs `canvases:write` and `files:read`, as design reporting does.

Scheduled runs use the most recent configured local cutoff even if GitHub starts
late. With `weekdays: [0, 1, 2, 3, 4]`, Monday covers Friday 08:00 through Monday
08:00; Tuesday through Friday cover the previous morning through that morning.
The first Monday includes Friday’s workday and the weekend even without an earlier
checkpoint. DST changes preserve local boundaries without gaps (a fall-back Monday
covers 73 actual hours). Generation starts at the scheduled time; Slack arrives after
collection and generation, and GitHub can delay scheduled starts. It is not an
exact-minute delivery guarantee. Review evidence is freshly collected for 30 days;
open drafts and reviewers are collected even when their last update is older.
Current metadata is clearly separate from cutoff-bounded merge/discussion evidence.

The weekly collector remains unchanged by default. Daily collection opts into
all open PRs and includes current head-SHA checks and requested reviewers. A query
reaching GitHub's 1,000-result search limit blocks publication rather than silently
omitting PRs. CI collection pages check suites on the current default-branch commit; per-PR
check rollups identify checks on the current PR head. Discussions use paginated
GraphQL comments, reviews and inline threads, avoiding thousands of REST requests
when rebuilding the 30-day history. Timezone data ships with the package for Windows.

## Preview and recovery

`workflow_dispatch` should default to `post-to-slack: false`; it preserves the same
sources, coverage and message artifact without writing a checkpoint or contacting
Slack. An optional aware ISO cutoff previews a prior window; open PR/reviewer/CI
states remain current, not reconstructed historical snapshots.

Before posting, a checkpoint on the caller's dedicated state branch records the
prepared artifact run ID and content digest. Every message has a stable metadata
key and a durable intent/receipt. Only a fully posted thread advances last_cutoff.
The next run resumes a pending thread from that exact artifact, without regenerating
its messages. A later run covers any missed days from the last successful cutoff.
A successful cutoff is never reposted, even if a workflow is rerun. Receipts for
older completed cutoffs are pruned when the next thread starts, keeping the
checkpoint small. GitHub collection errors preserve the CLI diagnostic in the
manifest, so quota and permission failures are distinguishable.

If a network loss occurs after Slack may have accepted a message, recovery attempts
to find its metadata in Slack history/replies. This requires history permissions;
some bot installations cannot read public-channel replies. If recovery is unavailable
or ambiguous, the process stops rather than blindly duplicating a message. An
operator must inspect the thread and repair that intent on the state branch with the
verified timestamp, or clear it only after verifying no message was accepted. An
explicit Slack rejection is safe to retry. Expired/unavailable artifacts block
recovery; artifact retention is 45 days. GitHub workflow failures remain visible in
Actions. No extra failure message is posted to the team channel.

The generator is given no Slack token or write credentials. It must not change
issues, deployments or the source mirror. Evidence and generated messages are
uploaded even on failure when available. Raw evidence stays in artifacts rather
than being committed into the mirror or a new Linear report document every day.

## Review evidence checks

Preparation writes `review-learning-evidence.json` with exact 30-day formal-review
and inline-comment totals and usable dated bodies. Current review snapshots and
bodies edited after cutoff are excluded from the learning corpus. The generator
writes `review-learning.json`, recording inspected PRs and the comment URLs behind
any repeated problem. Validation rejects incorrect totals, fabricated citations,
patterns supported by only one PR, and missing top-level citations. Empty patterns
need an explicit reason. These checks establish provenance; they cannot prove that
a generated interpretation is sound. The prompt requires plain before/after language,
explicit roles for people and observed CI check names instead of blanket health claims.

Generation validates the draft and permits at most two focused revisions against
the same prepared sources. Evidence JSON and inventory replies are hashed before
model calls; changing either blocks the run. Revisions do not recollect sources.
Pending publication artifacts are never rewritten. An isolated preview may supply
`evidence-run-id` to download an earlier artifact from the same caller repository
and repair its invalid draft. Evidence reuse is rejected for publishing runs.

## Canvas delivery and recovery

Canvas mode reuses `issueclaw.slack_canvas`, the publisher used by design weekly
reports. Validation assembles the full narrative and immutable complete inventory
into `canvas.md`. Its title and content are included in the pending artifact digest.
The shared Canvas publisher can checkpoint each creation intent, ID and confirmed
URL through a callback; daily reporting stores these on its dedicated state branch.
The confirmed link is appended to the TLDR in memory, and only that message is sent.
A failure fetching the permalink retries with the known canvas ID; an uncertain
creation outcome stops for inspection. Record the recovered ID and clear the canvas
receipt's pending marker only after checking Slack. A cutoff completes only when
both the Canvas and its TLDR are delivered. New cutoffs replace the old receipt;
previous reports remain accessible in Slack. Previews create neither Canvas nor
Slack messages, and retain the assembled Markdown as an artifact.
