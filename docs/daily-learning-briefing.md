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
the default. Set `canvas_inventory: "merged"` to append only the window's merged
PRs. Open/draft work is curated in the narrative (at most eight linked PRs), with
named involvement and concrete next decisions; the full open/draft and ticket
inventories remain private evidence artifacts and still require complete audits.
The generator uses Claude Sonnet 5.5 (`claude-sonnet-5-5`) for drafting and revisions;
both reporting and video research use an Opus 5.5 advisor and Haiku subagents.
Video research uses Sonnet 5.5 at medium effort (see below).
The full Canvas report has no 550-word limit; only the TLDR is capped
at 180 words in paragraph mode. Set `slack_summary_format: "titles"` for a contents
message: one bullet per narrative topic heading, in Canvas order with lead names,
plus a playful invitation of at most 25 words. Generic What changed/Learning labels
are omitted when they have child topics. Waiting on people, Active work and CI
require concrete child headings, shown as nested Slack bullets: people and their
next actions/work, or repositories and observed check statuses. Learning titles
describe the practical action or capability without a fixed slogan. Inventory appendices and headings inside
code examples are excluded. Bullets are assembled from the report rather than
rewritten by the model; their total is bounded by Slack message size rather than
the paragraph word cap. The previous successful invitation is checkpointed, and
repeating it blocks validation for a focused revision. Pending artifacts retain
their original message and invitation. Keep company
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

To replace a morning briefing with an early manual publication, pass `run-early:
true` to the reusable workflow and add that morning's local ISO date to the caller
config's `skip_scheduled_dates`, for example `["2026-10-06"]`. The planning job skips
generation and publication only for a scheduled run on that exact local date;
manual runs and subsequent dates remain enabled. Early mode ends coverage at the
planning job's actual UTC time, never at a future morning. It cannot be combined
with historical cutoff/evidence reuse. Coverage starts at the last successfully
published cutoff, and the next normal briefing starts at the early report's cutoff.
The exclusion does not change delivery checkpoints; verify early publication
succeeded before relying on the replaced morning's skip.

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
recovery; artifact retention is 90 days. GitHub workflow failures remain visible in
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
reports. Validation assembles the full narrative and the configured inventory appendix
into `canvas.md`; complete source inventories remain in the artifact. Its title and content are included in the pending artifact digest.
The shared Canvas publisher can checkpoint each creation intent, ID and confirmed
URL through a callback; daily reporting stores these on its dedicated state branch.
The confirmed link is appended to the TLDR in memory, and only that message is sent.
A failure fetching the permalink retries with the known canvas ID; an uncertain
creation outcome stops for inspection. Record the recovered ID and clear the canvas
receipt's pending marker only after checking Slack. A cutoff completes only when
both the Canvas and its TLDR are delivered. New cutoffs replace the old receipt;
previous reports remain accessible in Slack. Previews create neither Canvas nor
Slack messages, and retain the assembled Markdown as an artifact.

An operator can pass `revision-notes` to revise an existing preview even when its
structural checks pass. Notes are passed through a quoted environment variable,
not interpolated into shell code. Source/inventory immutability and audit checks
still apply. A pending publication always skips the generator, including these
notes. Callers should expose notes as a preview-only input; scheduled runs use the
normal prompt. The revised artifact can then be reserved for exact publication.

## Waiting attribution

Daily collection retains a complete current discussion snapshot, paginated commit
identities/dates and human review-request/readiness/reopen/force-push events for
open PRs. This current activity is separate from the cutoff-bounded learning corpus.
Each PR record and inventory row includes a `waiting` baseline with named people,
reason, evidence, last movement and an as-of timestamp. Four elapsed days (96 hours)
without substantive movement returns the next action to the author, overriding
pending review requests. Otherwise feedback without a later author commit/comment
waits on the author; pending review requests wait on named reviewers. Author
follow-up clears that feedback wait. Recent drafts without a review dependency
remain active work. CI/label churn and bot comments never reset inactivity.

The generator must also read reviews posted as ordinary issue comments, cite them
and compare later author activity: formal review requests can remain even after
such a review. Teammate changes are credited but do not become author follow-up.
Missing snapshots or unattributed possible follow-up produce an unverified person,
not a claim that the author has done nothing. Head changes during paginated activity
collection block publication for retry. Retained commit timestamps are not a complete
push log, and deleted comments or commits removed from the branch are unavailable.
Waiting items remain curated; this does not add the old open backlog to the Canvas.

## Learning lessons and videos

The daily briefing can turn each lesson it teaches into a short lesson with a video. The
caller opts in by passing `learning-videos-repository` and a reviewed
`learning-videos-ref` to the reusable workflow, plus `learning_videos.max` (default 1) in its config. Optional
`learning_videos.instructions` holds the caller's own guidance for the lesson and
its video (style, sound, tone); it is appended to the agent's prompt.
The kit is a repository following promo-videos' `src/learnings/AGENT.md`, such
as `aviadr1/promo-videos`. `REPOS_READ_TOKEN` must read it, or the caller supplies
`VIDEOS_READ_TOKEN`.

The briefing's `## Learning` section holds one or two `###` lessons from recent
work, of any kind worth sharing. Examples: a surprising root cause, a distributed
failure mode, a concurrency guard, a new primitive or system, an algorithm or
heuristic, a measured performance or scaling change, a CI fix, a restructuring,
a convention turned into a check, a testing or observability technique. A problem
repeated across reviews is one strong signal among these, not the only one. The
prompt lists kinds to skip (releases, bump PRs, plumbing, series follow-ups) and
how to rank candidates; this list came from sampling 65 merged PRs over 40 days.
Published lessons are remembered on the state branch (`taught_lessons`, the
last 60) and passed to the next briefing as `window.json` `previous_lessons`, so
it doesn't teach the same lesson twice.

After the briefing is drafted, the `learn` command gives each of those lessons (up
to the limit) to a separate agent: Claude Sonnet 5.5 (`claude-sonnet-5-5`) at medium
effort, with an Opus 5.5 advisor, Haiku subagents and a 45-minute cap. The agent
gets the briefing's draft (`draft.md`) and any review comments it cites
(`comments.json`), digs into the PRs and code with read-only GitHub access, then
writes `learnings/<n>/learning.md` (three or four short paragraphs, e.g. Problem /
Root cause / Fix / Rule, or Problem / Idea / How it works / Takeaway) and
`learning.json` (slug, title, rule, sources),
and renders `video.mp4` with the kit. Its output is used as written. A lesson is
dropped only if the agent wrote no text, title or rule, and it is published without
a video if no video was made. If the agent leaves before its render finishes, the
kit's `render-learning.sh` is run to finish it. Nothing here can block the briefing:
agent and render failures are recorded in `error.txt` or `render.log`, and the
briefing publishes without the lesson. `learnings.json` records the lessons; a
rerun, revision or evidence-reuse preview reuses it instead of running the researcher again.
Previews keep each video in the artifact for review.

In the Canvas and its Slack topic list, each lesson replaces the learning the
briefing wrote, in the same place: the section the lesson came from takes the
lesson's title at the same level, or, if it is the "Learning" heading itself, the
lesson goes under it. A video
placeholder is filled at publication. A learning the briefing never wrote up is not
added. `report.md` keeps the briefing's text, so the review-citation audit is
unchanged. The lessons and the videos' hashes are part of the pending digest. At publication, each
video is uploaded once and embedded in the Canvas through its Slack file link,
and the TLDR gains a **Learning:** line with each lesson's rule. The formatted
briefing post carries the Canvas file as its card. A separate channel post follows
with one line summarizing the lesson and those same uploaded video file IDs.
The Canvas references that shared video, so channel members can open it there too.
Both posts and their attachments are verified before the coverage cutoff advances.
A failed attachment retries against the checkpointed message without posting another
or uploading another copy. Uploading needs the bot's `files:write` scope. If Slack refuses an upload,
the refusal is recorded for that cutoff: the Canvas has no embed (it stays identical
on retry) and the TLDR is posted as plain text. Canvas embedding of video files
follows Slack's file-embed syntax; if a workspace shows a link rather than a player,
the video is still in its separate Slack post.

Messages use Slack's `markdown_text` input so topic bullets and their nested items
become native lists. Video attachment preserves the returned rich-text blocks;
updating only `text` would discard their formatting.
The confirmed Canvas link is the first line, labeled **Your daily briefing canvas**.
The title and bullets follow it; the changing invitation stays at the bottom.

For a clip recovered after a briefing completed, the reusable
`attach-briefing-video.yml` workflow accepts the original artifact run and an
already uploaded Slack file ID. It calls `daily_briefing attach-video --file-id F…`
with the caller's bot credentials. Only the latest completed cutoff can be repaired,
and a pending publication blocks the repair. It preserves the message text and
coverage cutoff and records the attachment separately. The caller must serialize
this workflow with publication. A separately repaired Canvas should reference
the same file ID.

The recovery workflow's optional `format-message` input reparses the original TLDR
as Markdown and verifies Slack returns native lists. It reconstructs the Markdown
from the original artifact and confirmed Canvas URL, then requires the current
message text to match exactly before changing presentation. Its file attachment
and coverage cutoff stay in place.

The optional `split-delivery` recovery input restores the Canvas card on the
original briefing and posts the recovered video with its lesson rule in a separate
channel message. Both message timestamps are checkpointed, so retrying the repair
does not duplicate the follow-up. Formatting and split repairs cannot be combined.


## Readable videos, selection audits and review walkthroughs

The Sonnet 5.5 report runner now uses `--advisor claude-opus-5-5` and
`CLAUDE_CODE_SUBAGENT_MODEL=haiku`. The Sonnet 5.5 video researcher also uses
`--advisor claude-opus-5-5`, medium effort, and Haiku for bounded extraction. Candidate comparisons and advisor
conclusions are concise decision records; they do not claim to expose hidden
model reasoning. The generator writes `selection-audit.json` comparing reuse,
evidence, tradeoffs and why each candidate won or lost across the merged work.

The reusable workflow accepts `generation-runner` (default `ubuntu-latest`) so
consumers can select a larger existing runner for research/rendering. Planning and
publishing keep standard runners. Runner traces include CPU count and runner name.

Optional caller settings under `learning_videos`:

- `playback_speed: 0.5` delivers the rendered clip at half speed with pitch-preserving
  audio. The inspected 42.5-second clip becomes about 85 seconds. Conversion is
  applied once before publication; failed conversion suppresses the video, retaining
  the lesson text and error. The prompt targets 75–120 final seconds for a lesson.
- `review: true` adds one substantial open PR walkthrough without consuming `max`
  lesson slots. The report compares eligible PRs and writes `review-selection.json`.
  Selection requires the collected open state, reviewer dependency and head SHA;
  approved, draft and author-blocked work are excluded. No suitable candidate gets
  an explicit reason. Review videos target 3–5 minutes, inspect source and tests at
  the recorded head, and explain purpose, mechanism, review difficulty and specific
  questions with evidence and unknowns. Previously covered PR/heads are remembered.
- `quality_checks: true` requires research, question/answer notes, a storyboard,
  per-scene QA stills and QA notes. The gate checks the recorded final timing against
  the actual video duration and requires reading time after the final reveal. Word
  counts ignore punctuation-only separators. The video agent must run this same
  validator before finishing and fix failures, including an 8-second final end card. These
  checks cannot prove the agent's timing claims match every rendered frame; still
  inspection and human viewing remain necessary. A failed gate retains text and
  the failed video in the private artifact but does not upload the clip to Slack.
- `attach_to_prs: true` posts one comment per video/source PR, containing the team
  Slack video permalink and a link to the generation run/artifacts. This is a video
  link, not a native GitHub video upload; viewers need team Slack access. Review
  videos attach only to their selected PR and refuse a changed head or closed/draft
  state. Lesson videos attach to the PR URLs cited as sources in configured repos.

Comment publishing happens only after Slack publication; previews never comment.
An optional `PR_COMMENT_TOKEN` needs issue-comment write access on the source
repositories. It falls back to `REPOS_READ_TOKEN`, which must have that write scope
for this feature despite its historical name. Generation still receives only the
existing read token. Missing access fails the attachment step visibly and leaves
per-target receipts, while the already delivered Slack briefing is preserved.
Rerun the publish job to recover: comments are found by authenticated author and
video-hash marker, so even an accepted write with a lost response is not duplicated.

Start artifact review at `TRACE-INDEX.md`, which links each completed or failed video
attempt to its questions, evidence, QA, timing and source.
The `daily-learning-briefing` artifact retains selection audits, frozen evidence,
exact model prompts and requested models, structured tool transcripts, runner and
pinned tooling/kit versions, source/captured assets, questions, research, storyboard,
QA stills, pacing measurements, MP4s and outcomes for 90 days. Source is copied even
when an agent fails. `daily-learning-briefing-delivery` separately retains publication
state and PR-comment receipts after publication, including partial failures. Neither
artifact serializes credential environments. The rendered video's SHA-256 links its
pacing record to the PR-comment receipt. Source inspection/QA transcripts may contain
private repository material; artifacts stay in the caller repository.
