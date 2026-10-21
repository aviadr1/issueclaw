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

test('thinking heartbeats do not reset meaningful activity and completed phase time stays fixed', () => {
  const progress = new Progress(0);
  progress.accept({type: 'system', subtype: 'thinking_tokens'}, 5000);
  assert.equal(progress.snapshot(6000).activity_seconds, 6);
  progress.accept({type: 'result', duration_ms: 7000, duration_api_ms: 6000, usage: {output_tokens: 1200}}, 7000);
  assert.equal(progress.snapshot(20000).elapsed_seconds, 7);
  assert.equal(progress.snapshot(20000).reported_output_tokens, 1200);
});
