# Independent briefing writers: controlled text experiment

This opt-in reusable workflow compares the current briefing generator with fresh
section writers. It does not alter the scheduled pipeline. It has read-only GitHub
permissions and no video, Slack, PR-comment or media-publication step or secret.

Both arms use the same previously collected `daily-learning-briefing` artifact,
current caller configuration and editorial instructions. Preparation copies only
source evidence and inventory messages; earlier reports, lessons and videos are
excluded. Input file hashes and editorial/prompt hashes make differences visible.
The experiment preserves the optional review walkthrough as text.

```
baseline: frozen evidence -> current writer/helpers/advisor -> validate/repair
split:    frozen evidence -> curator -> capability writers (up to four)
                                   +-> queue/review writer
                                   +-> CI writer
                                   +-> learning/review-pattern writer
                         -> deterministic assembly -> independent reader
                         -> up to three targeted corrections -> validate
```

The split uses at most four simultaneous Claude sessions with the same main model,
advisor and helper model as the baseline. Each invocation has a $5 CLI budget and
a fifteen-minute timeout; at most twelve split invocations are launched. These
are CLI bounds, not an invoice guarantee. The curator chooses up to four capability
groups; this initial experiment uses one learning writer and one CI writer, rather
than spawning separately for every lesson and repository. Evidence is shared and
fingerprinted; private contexts/output paths are not a filesystem sandbox.

Each arm records generation seconds (including its repairs), reported CLI cost,
per-invocation token/model usage, missing-cost flags, validation outcome and evidence
hashes in `experiment-metrics.json`. Compare total workflow/job duration separately:
it also includes runner provisioning, installation, downloading and trace upload.
The one-time collection and excluded video costs are not attributed to either arm.
Do not add nested LangSmith token costs on top of CLI totals. Missing results mean
unknown cost, not free work.

LangSmith is required for the experiment. Every CLI session gets its own state file,
session ID and metadata (arm, stage, source evidence run and CI run). The `ci` stage
has its own trace. A final API read verifies remote trace roots and saves links in
`langsmith-traces.json`; failed verification fails the job while retaining local
logs. Tracing uses the existing pinned Claude plugin, with secret redaction enabled.

Evaluate reports blind to arm and timing/cost before decoding their identities:
check factual status, merge versus rollout/adoption, reader action and prerequisites,
current waiting ownership, actual CI coverage, relevance, useful lessons, citations,
coverage and readability. Record concrete errors, not just subjective scores. A
faster or cheaper invalid report is not a quality-neutral win. One paired run is a
feasibility observation, not evidence of general superiority; repeat across quiet,
busy and cross-repository days before changing the default.
