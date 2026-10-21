import assert from 'node:assert/strict';
import {test} from 'node:test';
import {mkdtempSync, mkdirSync, appendFileSync, writeFileSync, readFileSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {Progress, observe, supervise, loadUploader} from '../src/issueclaw/briefing-progress.mjs';

test('progress measures tool waits separately and never emits prompt or tool payloads', () => {
  const p = new Progress(1000);
  p.accept({type: 'assistant', timestamp: new Date(2000).toISOString(), message: {id: 'm1', usage: {output_tokens: 12}, content: [{type: 'tool_use', id: 't1', name: 'Bash', input: {command: 'node scripts/learning-review.mjs secret-topic /private'}}]}}, 2000);
  const live = p.snapshot(5000);
  assert.equal(live.activity, 'early_frames');
  assert.equal(live.activity_seconds, 3);
  p.accept({type: 'user', timestamp: new Date(6000).toISOString(), message: {content: [{type: 'tool_result', tool_use_id: 't1', content: 'SECRET'}]}}, 6000);
  p.accept({type: 'result', duration_api_ms: 2000, num_turns: 3}, 7000);
  const final = p.snapshot(8000);
  assert.equal(final.tool_seconds.early_frames, 4);
  assert.equal(final.api_seconds, 2);
  assert.equal(final.reported_output_tokens, 12);
  assert.ok(!JSON.stringify(final).match(/SECRET|secret-topic|private/));
});

test('message parts count usage once and a pending advisor remains visible', () => {
  const p = new Progress(0);
  const event = {type: 'assistant', message: {id: 'same', usage: {output_tokens: 10}, content: []}};
  p.accept(event, 1000); p.accept(event, 1000);
  p.accept({type: 'assistant', message: {content: [{type: 'server_tool_use', id: 'advisor', name: 'advisor', input: {prompt: 'secret'}}]}}, 2000);
  assert.equal(p.snapshot(5000).activity, 'advisor');
  assert.equal(p.snapshot(5000).reported_output_tokens, 10);
  p.accept({type: 'assistant', message: {content: [{type: 'advisor_tool_result', tool_use_id: 'advisor', content: 'private'}]}}, 6000);
  assert.equal(p.snapshot(7000).activity, 'model');
});


test('incremental observation handles partial JSON and ignores previous preview archives', async () => {
  const root = mkdtempSync(join(tmpdir(), 'briefing-progress-'));
  try {
    const dir = join(root, 'learnings/1');
    mkdirSync(dir, {recursive: true});
    const file = join(dir, 'research.log');
    writeFileSync(file, 'stderr warning\n{"type":"result",');
    const streams = new Map();
    assert.equal((await observe(root, streams))[0].phases.research.activity, 'model');
    appendFileSync(file, '"duration_api_ms":1250,"num_turns":4}\n');
    assert.equal((await observe(root, streams))[0].phases.research.api_seconds, 1.3);
    assert.equal((await observe(root, streams))[0].phases.research.turns, 4);
  } finally { rmSync(root, {recursive: true, force: true}); }
});

test('observer preserves child failure and writes a final local snapshot without credentials', async () => {
  const root = mkdtempSync(join(tmpdir(), 'briefing-child-'));
  try {
    assert.equal(await supervise(root, [process.execPath, '-e', 'process.exit(7)']), 7);
    const final = JSON.parse(readFileSync(join(root, 'progress/progress.json'), 'utf8'));
    assert.equal(final.finished, true);
    assert.equal(final.exit_code, 7);
  } finally { rmSync(root, {recursive: true, force: true}); }
});


test('the installed artifact client loads through its ESM export', async () => {
  const directory = fileURLToPath(new URL('../tools/briefing-progress/', import.meta.url));
  const client = await loadUploader(directory);
  assert.equal(typeof client.uploadArtifact, 'function');
});

test('thinking heartbeats do not reset activity and a result does not finish a live process', () => {
  const progress = new Progress(0);
  progress.accept({type: 'system', subtype: 'thinking_tokens'}, 5000);
  assert.equal(progress.snapshot(6000).activity_seconds, 6);
  progress.accept({type: 'result', duration_ms: 7000, duration_api_ms: 6000, usage: {output_tokens: 1200}}, 7000);
  assert.equal(progress.snapshot(20000).elapsed_seconds, 20);
  assert.notEqual(progress.snapshot(20000).activity, 'finished');
  assert.equal(progress.snapshot(20000).reported_output_tokens, 1200);
});


test('parallel chapter helpers are visible individually and retire independently', () => {
  const progress = new Progress(0);
  progress.accept({type: 'assistant', message: {content: [
    {type: 'tool_use', id: 'a', name: 'Agent', input: {subagent_type: 'chapter-worker', prompt: 'private evidence'}},
    {type: 'tool_use', id: 'b', name: 'Agent', input: {subagent_type: 'chapter-repair'}},
  ]}}, 1000);
  assert.deepEqual(progress.snapshot(3000).active_helpers, [
    {worker: 'chapter-worker', elapsed_seconds: 2},
    {worker: 'chapter-repair', elapsed_seconds: 2},
  ]);
  progress.accept({type: 'user', message: {content: [{type: 'tool_result', tool_use_id: 'a', content: 'done'}]}}, 4000);
  assert.deepEqual(progress.snapshot(5000).active_helpers, [{worker: 'chapter-repair', elapsed_seconds: 4}]);
  assert.ok(!JSON.stringify(progress.snapshot(5000)).includes('private evidence'));
});


test('background worker remains observable after its launch tool returns', () => {
  const progress = new Progress(0);
  progress.accept({type: 'assistant', message: {content: [{type: 'tool_use', id: 'launch', name: 'Agent', input: {subagent_type: 'chapter-worker'}}]}}, 1000);
  progress.accept({type: 'user', message: {content: [{type: 'tool_result', tool_use_id: 'launch', content: 'Async agent launched successfully'}]}}, 1100);
  progress.accept({type: 'system', subtype: 'task_started', task_type: 'local_agent', task_id: 'worker', tool_use_id: 'launch', subagent_type: 'chapter-worker'}, 1200);
  assert.deepEqual(progress.snapshot(5000).active_helpers, [{worker: 'chapter-worker', elapsed_seconds: 4}]);
  progress.accept({type: 'system', subtype: 'task_updated', task_id: 'worker', patch: {status: 'completed', end_time: 7000}}, 7000);
  progress.accept({type: 'system', subtype: 'task_notification', task_id: 'worker', status: 'completed'}, 7001);
  assert.deepEqual(progress.snapshot(8000).active_helpers, []);
  assert.equal(progress.snapshot(8000).completed_helpers, 1);
});


test('result turns accumulate once while later notifications keep the process live', () => {
  const progress = new Progress(1000);
  const first = {type: 'result', uuid: 'result-a', session_id: 'session', result_index: 0, duration_ms: 198000, duration_api_ms: 207000, num_turns: 20, usage: {output_tokens: 23000}, modelUsage: {private: {outputTokens: 23000}}};
  progress.accept(first, 199000);
  assert.notEqual(progress.snapshot(200000).activity, 'finished');
  progress.accept({type: 'assistant', message: {id: 'next-message', content: [{type: 'tool_use', id: 'write', name: 'Edit', input: {file_path: '/private', old_string: 'SECRET'}}]}}, 201000);
  assert.equal(progress.snapshot(202000).activity, 'writing');
  progress.accept({type: 'user', message: {content: [{type: 'tool_result', tool_use_id: 'write'}]}}, 203000);
  progress.accept({...first, uuid: 'duplicate-delivery'}, 204000);
  progress.accept({type: 'result', uuid: 'result-b', session_id: 'session', result_index: 1, duration_ms: 600, duration_api_ms: 0, num_turns: 0, usage: {output_tokens: 0}}, 205000);
  const live = progress.snapshot(210000);
  assert.equal(live.elapsed_seconds, 209);
  assert.equal(live.api_seconds, 207);
  assert.equal(live.turns, 20);
  assert.equal(live.result_turns, 2);
  assert.equal(live.reported_turn_seconds, 198.6);
  assert.equal(live.reported_output_tokens, 23000);
  assert.notEqual(live.activity, 'finished');
  assert.ok(!JSON.stringify(live).match(/SECRET|private/));
});

test('only process timing marks a phase finished and keeps its full wall time', async () => {
  const root = mkdtempSync(join(tmpdir(), 'briefing-timing-'));
  try {
    const dir = join(root, 'learnings/1');
    mkdirSync(dir, {recursive: true});
    writeFileSync(join(dir, 'agent.log'), JSON.stringify({type: 'result', result_index: 0, duration_ms: 600, duration_api_ms: 400, num_turns: 1}) + '\n');
    const streams = new Map();
    const started_at = new Date(1000).toISOString();
    writeFileSync(join(dir, 'agent.timing.json'), JSON.stringify({started_at, status: 'running'}));
    const live = (await observe(root, streams, 21000))[0].phases.agent;
    assert.equal(live.elapsed_seconds, 20);
    assert.notEqual(live.activity, 'finished');
    writeFileSync(join(dir, 'agent.timing.json'), JSON.stringify({started_at, ended_at: new Date(31000).toISOString(), duration_ms: 30000, status: 'completed'}));
    const final = (await observe(root, streams, 40000))[0].phases.agent;
    assert.equal(final.activity, 'finished');
    assert.equal(final.elapsed_seconds, 30);
    assert.equal(final.wall_seconds, 30);
    assert.equal(final.api_seconds, 0.4);
    writeFileSync(join(dir, 'agent.timing.json'), JSON.stringify({started_at, ended_at: new Date(31000).toISOString(), duration_ms: 30000, status: 'failed'}));
    assert.equal((await observe(root, streams, 40000))[0].phases.agent.activity, 'failed');
  } finally { rmSync(root, {recursive: true, force: true}); }
});


test('final review recovery has its own live phase and process duration', async () => {
  const root = mkdtempSync(join(tmpdir(), 'briefing-review-'));
  try {
    const dir = join(root, 'learnings/1');
    mkdirSync(dir, {recursive: true});
    writeFileSync(join(dir, 'final-review-1.log'), JSON.stringify({type: 'assistant', message: {content: [{type: 'server_tool_use', id: 'review', name: 'advisor'}]}}) + '\n');
    writeFileSync(join(dir, 'final-review-1.timing.json'), JSON.stringify({started_at: new Date(1000).toISOString(), status: 'running'}));
    const phase = (await observe(root, new Map(), 11000))[0].phases['final-review-1'];
    assert.equal(phase.activity, 'advisor');
    assert.equal(phase.elapsed_seconds, 10);
  } finally { rmSync(root, {recursive: true, force: true}); }
});


test('queued notifications do not double cumulative API counters', () => {
  const progress = new Progress(0);
  for (const [result_index, duration_api_ms, num_turns] of [[0, 207944, 20], [1, 0, 0], [2, 854052, 10], [3, 854052, 54]]) {
    progress.accept({type: 'result', session_id: 'session', result_index, duration_api_ms, num_turns}, 1000);
  }
  assert.equal(progress.snapshot(2000).api_seconds, 854.1);
  assert.equal(progress.snapshot(2000).turns, 54);
});
