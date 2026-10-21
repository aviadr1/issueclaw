import {spawn} from 'node:child_process';
import {copyFileSync, createReadStream, existsSync, mkdirSync, readFileSync, readdirSync, renameSync, statSync, writeFileSync, appendFileSync} from 'node:fs';
import {join, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const activity = (name, input = {}) => {
  if (name === 'advisor') return 'advisor';
  if (name === 'Agent' || name === 'Task') return 'helper';
  if (name === 'Write' || name === 'Edit') return 'writing';
  if (name === 'Read') return /\.(png|jpg)$/.test(input.file_path ?? '') ? 'visual_review' : 'reading';
  const command = input.command ?? '';
  if (/render-learning\.(sh|mjs)/.test(command)) return 'render';
  if (/learning-review\.mjs/.test(command)) return 'early_frames';
  if (/(?:node\s+scripts\/learning-check\.mjs|npm\s+run\s+typecheck)/.test(command)) return 'layout_check';
  if (/briefing_trace\.py|learning-qa\.mjs/.test(command)) return 'quality_check';
  if (/gh (api|pr)/.test(command)) return 'research';
  return 'tool';
};
const seconds = (ms) => Math.round(ms / 100) / 10;

export class Progress {
  constructor(started = Date.now()) {
    this.started = started;
    this.last = started;
    this.pending = new Map();
    this.helperCalls = new Map();
    this.helperTasks = new Map();
    this.completedHelpers = new Set();
    this.messages = new Map();
    this.totals = {};
    this.calls = {};
    this.results = new Map();
  }
  accept(event, now = Date.now()) {
    if (event.type === 'system') {
      if (event.subtype === 'task_started' && event.task_type === 'local_agent') {
        const call = this.helperCalls.get(event.tool_use_id);
        this.helperTasks.set(event.task_id, {toolUseId: event.tool_use_id, at: call?.at ?? now, worker: call?.worker});
      }
      const status = event.subtype === 'task_updated' ? event.patch?.status : event.subtype === 'task_notification' ? event.status : null;
      if (['completed', 'failed', 'stopped'].includes(status) && this.helperTasks.has(event.task_id)) {
        this.helperTasks.delete(event.task_id);
        this.completedHelpers.add(event.task_id);
      }
      return;
    }
    if (!['assistant', 'user', 'result'].includes(event.type)) return;
    const stamp = Date.parse(event.timestamp);
    const at = Number.isFinite(stamp) ? stamp : now;
    this.last = Math.max(this.last, at);
    const msg = event.message;
    if (msg?.id && msg.usage) this.messages.set(msg.id, msg.usage.output_tokens ?? 0);
    for (const block of Array.isArray(msg?.content) ? msg.content : []) {
      if (block.type === 'tool_use' || block.type === 'server_tool_use') {
        if (this.pending.has(block.id)) continue;
        if (block.type === 'tool_use' && !event.parent_tool_use_id) {
          for (const pending of this.pending.values()) {
            if (pending.label === 'advisor' && !pending.parent && (!msg.id || pending.messageId !== msg.id)) pending.resumed = true;
          }
        }
        const label = activity(block.name, block.input);
        const worker = label === 'helper' ? block.input?.subagent_type : undefined;
        this.pending.set(block.id, {label, at, worker, parent: event.parent_tool_use_id, messageId: msg.id});
        if (label === 'helper') this.helperCalls.set(block.id, {at, worker});
        this.calls[label] = (this.calls[label] ?? 0) + 1;
      } else if (block.type === 'tool_result' || block.type === 'advisor_tool_result') {
        const pending = this.pending.get(block.tool_use_id);
        if (pending) {
          this.totals[pending.label] = (this.totals[pending.label] ?? 0) + Math.max(0, at - pending.at);
          this.pending.delete(block.tool_use_id);
        }
      }
    }
    if (event.type === 'result') {
      const key = event.result_index != null ? `${event.session_id ?? ''}:${event.result_index}` : event.uuid ?? JSON.stringify([event.timestamp, event.duration_ms, event.duration_api_ms, event.num_turns]);
      this.results.set(key, {
        api_ms: event.duration_api_ms ?? 0, turns: event.num_turns ?? 0,
        duration_ms: event.duration_ms ?? 0, output_tokens: event.usage?.output_tokens ?? 0,
      });
    }
  }
  snapshot(now = Date.now(), timing = null) {
    const current = [...this.pending.values()].filter((tool) => !tool.resumed).sort((a, b) => a.at - b.at)[0];
    const complete = ['completed', 'failed'].includes(timing?.status) && Number.isFinite(timing.duration_ms);
    const totals = [...this.results.values()].reduce((sum, turn) => ({
      api_ms: Math.max(sum.api_ms, turn.api_ms), turns: sum.turns + turn.turns,
      duration_ms: sum.duration_ms + turn.duration_ms, output_tokens: sum.output_tokens + turn.output_tokens,
    }), {api_ms: 0, turns: 0, duration_ms: 0, output_tokens: 0});
    return {
      elapsed_seconds: seconds(complete ? timing.duration_ms : now - this.started),
      activity: complete ? (timing.status === 'failed' ? 'failed' : 'finished') : (current?.label ?? 'model'),
      activity_seconds: complete ? 0 : seconds(now - (current?.at ?? this.last)),
      seconds_since_event: seconds(now - this.last),
      reported_output_tokens: Math.max(totals.output_tokens, [...this.messages.values()].reduce((a, b) => a + b, 0)),
      api_counter: 'maximum_reported',
      api_seconds: seconds(totals.api_ms), turns: totals.turns, result_turns: this.results.size,
      reported_turn_seconds: seconds(totals.duration_ms),
      calls: this.calls,
      completed_helpers: this.completedHelpers.size,
      unresolved_advisor_calls: [...this.pending.values()].filter((tool) => tool.resumed).length,
      active_helpers: [...this.helperTasks.values(), ...[...this.pending.entries()]
        .filter(([id, tool]) => tool.label === 'helper' && ![...this.helperTasks.values()].some((task) => task.toolUseId === id))
        .map(([, tool]) => tool)].map((tool) => ({
        worker: tool.worker ?? 'helper', elapsed_seconds: seconds(now - tool.at),
      })),
      tool_seconds: Object.fromEntries(Object.entries(this.totals).map(([k, v]) => [k, seconds(v)])),
      ...(complete ? {wall_seconds: seconds(timing.duration_ms), failed: timing.status === 'failed'} : {}),
    };
  }
}

export const observe = async (directory, streams, now = Date.now()) => {
  const lessons = join(directory, 'learnings');
  if (!existsSync(lessons)) return [];
  const result = [];
  for (const number of readdirSync(lessons).filter((n) => /^\d+$/.test(n)).sort()) {
    const phases = {};
    for (const phase of ['research', 'agent', 'final-review-1', 'final-review-2']) {
      const path = join(lessons, number, `${phase}.log`);
      if (!existsSync(path)) continue;
      const info = statSync(path);
      let timing;
      try { timing = JSON.parse(readFileSync(join(lessons, number, `${phase}.timing.json`), 'utf8')); } catch {}
      const recordedStart = Date.parse(timing?.started_at);
      const started = Number.isFinite(recordedStart) ? recordedStart : info.birthtimeMs;
      if (!streams.has(path) || info.size < streams.get(path).offset || streams.get(path).progress.started !== started) {
        streams.set(path, {offset: 0, partial: '', progress: new Progress(started)});
      }
      const stream = streams.get(path);
      if (info.size > stream.offset) {
        for await (const chunk of createReadStream(path, {start: stream.offset, end: info.size - 1, encoding: 'utf8'})) {
          const lines = (stream.partial + chunk).split('\n');
          stream.partial = lines.pop();
          for (const line of lines) {
            try { stream.progress.accept(JSON.parse(line), now); } catch { /* CLI stderr is not a JSON event. */ }
          }
        }
        stream.offset = info.size;
      }
      phases[phase] = stream.progress.snapshot(now, timing);
    }
    let outcome;
    try { outcome = JSON.parse(readFileSync(join(lessons, number, 'outcome.json'), 'utf8')).status; } catch {}
    result.push({lesson: Number(number), phases, outcome: ['video', 'text_only', 'failed', 'written'].includes(outcome) ? outcome : 'running'});
  }
  return result;
};

export const loadUploader = async (directory) => {
  const {DefaultArtifactClient} = await import(pathToFileURL(join(directory, 'upload.mjs')).href);
  return new DefaultArtifactClient();
};

export const supervise = async (directory, command) => {
  mkdirSync(directory, {recursive: true});
  const progressDir = join(directory, 'progress');
  mkdirSync(progressDir, {recursive: true});
  const snapshotPath = join(progressDir, 'progress.json');
  const streams = new Map();
  const started = Date.now();
  let uploader;
  if (process.env.BRIEFING_ARTIFACT_MODULE) {
    try {
      uploader = await loadUploader(resolve(process.env.BRIEFING_ARTIFACT_MODULE));
    } catch { console.warn('Progress artifact client unavailable; local progress and job logs continue.'); }
  }
  const childEnv = {...process.env};
  for (const key of ['ACTIONS_RUNTIME_TOKEN', 'ACTIONS_RESULTS_URL', 'ACTIONS_RUNTIME_URL']) delete childEnv[key];
  const child = spawn(command[0], command.slice(1), {stdio: 'inherit', env: childEnv, detached: process.platform !== 'win32'});
  let resolveExit;
  const exited = new Promise((resolve) => { resolveExit = resolve; });
  let finished = false;
  let exitCode = 1;
  child.on('error', () => { finished = true; resolveExit(); });
  child.on('exit', (code) => { exitCode = code ?? 1; finished = true; resolveExit(); });
  const stop = () => {
    if (!finished) {
      try { process.platform === 'win32' ? child.kill('SIGTERM') : process.kill(-child.pid, 'SIGTERM'); } catch {}
    }
  };
  process.on('SIGTERM', stop);
  process.on('SIGINT', stop);
  let sequence = 0;
  let lastUpload = 0;
  while (true) {
    let finalSnapshot = false;
    try {
      const data = {schema: 1, updated_at: new Date().toISOString(), elapsed_seconds: seconds(Date.now() - started),
        finished, exit_code: finished ? exitCode : null, lessons: await observe(directory, streams)};
      finalSnapshot = data.finished;
      writeFileSync(snapshotPath + '.tmp', JSON.stringify(data, null, 2) + '\n');
      renameSync(snapshotPath + '.tmp', snapshotPath);
      appendFileSync(join(progressDir, 'history.jsonl'), JSON.stringify(data) + '\n');
      console.log('BRIEFING_PROGRESS ' + JSON.stringify(data));
      if (uploader && (data.finished || Date.now() - lastUpload >= 60000)) {
        lastUpload = Date.now();
        const name = `learning-progress-${process.env.GITHUB_RUN_ATTEMPT ?? '1'}-${String(++sequence).padStart(3, '0')}`;
        try {
          const files = [snapshotPath];
          for (const lesson of data.lessons) {
            const from = join(directory, 'learnings', String(lesson.lesson));
            const to = join(progressDir, 'sessions', String(lesson.lesson));
            mkdirSync(to, {recursive: true});
            for (const file of readdirSync(from).filter((name) => /^(research|agent|final-review-[12])\.(log|prompt\.md|request\.json|trace\.json|timing\.json)$/.test(name))) {
              const target = join(to, file);
              copyFileSync(join(from, file), target);
              files.push(target);
            }
          }
          const uploaded = await uploader.uploadArtifact(name, files, progressDir, {retentionDays: 7});
          console.log(`Progress snapshot artifact: ${name} (${uploaded.id})`);
        } catch { console.warn('Progress snapshot upload failed; retrying at the next interval. Local history is preserved.'); }
      }
    } catch { console.warn('Progress snapshot failed; generation continues and the next interval retries.'); finalSnapshot = finished; }
    if (finalSnapshot) break;
    if (!finished) await Promise.race([exited, new Promise((resolve) => setTimeout(resolve, 15000).unref())]);
  }
  process.removeListener('SIGTERM', stop);
  process.removeListener('SIGINT', stop);
  return exitCode;
};

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const [directory, ...command] = process.argv.slice(2);
  if (!directory || !command.length) throw new Error('Usage: briefing-progress.mjs <output-dir> <command> [args...]');
  process.exitCode = await supervise(resolve(directory), command);
}
