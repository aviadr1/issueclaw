# Historical briefing experiment results

The independent split-writer experiment failed and was dropped. Its orchestration,
assembly, independent reader and resume implementation are not shipped. The
production single writer remains in use.

These observations are preserved from [PR #96](https://github.com/aviadr1/issueclaw/pull/96),
at [commit 93dbcec](https://github.com/aviadr1/issueclaw/commit/93dbcec231b75b79bf1d21e6a49253d948585446).
They are historical reported results, not new runs of the extracted tooling.

| Trial | Generation time | CLI estimate | Outcome |
| --- | ---: | ---: | --- |
| Existing single writer | 400.7 s | $1.5955 | Passed |
| Independent split writers | 632.4 s cumulative | $4.2781 | Failed: five requested repair targets exceeded its three-target bound |
| Single writer with stronger consumer instructions | 301.9 s | $1.2350 | Passed without repair; quality remained mixed |

A blinded review modestly favored the existing writer over the split result.
The split prototype demonstrated no benefit and does not warrant a production
switch.

The later [instruction trial](https://github.com/gigaverse-app/linear-git/actions/runs/39744751467)
was about 25% faster and 23% cheaper than the initial single-writer result. Source
evidence matched; consumer editorial configuration/instructions changed. Known
factual omissions persisted. Remote traces and the small report/metrics artifact
were saved. The full artifact upload failed because a tracing queue lock vanished
during archiving. The extracted workflows exclude that transient queue and keep
small result receipts in a separate artifact.

Timing excludes CI setup and diagnosis. CLI estimates include helpers/advisor and
attempted stages, not runner, implementation or evaluation costs. Instructions
were tuned on errors from this same snapshot. This is one feasibility observation,
not evidence of general quality improvement or architectural superiority. Raw
private transcripts remain with the original runs and are subject to their
artifact retention; this document preserves the reported results and provenance.

The durable extractions are historical manifest recovery and stable artifact
uploads, generic generation tracing/cost receipts, and a
[single-writer replay tool](briefing-replay.md) with separate evidence/editorial
hashes and the current production validator.
