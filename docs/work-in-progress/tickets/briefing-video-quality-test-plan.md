# Briefing video quality checks

- [x] Select a separate review walkthrough without consuming the lesson quota; verify the current open non-draft PR and recorded head.
- [x] Retiming uses real ffmpeg/ffprobe: final duration doubles with and without audio; failed retiming never publishes the rushed original.
- [x] Preserve prompt/model settings, inputs, composition source, timing and outcome on success and failure.
- [x] PR video comments target configured source repos, recover accepted-but-unacknowledged writes without duplicates, reject stale review heads, and record partial failures.
- [x] Existing Canvas, Slack, checkpoint and generation tests remain green; run lint, types and full Python suite.
