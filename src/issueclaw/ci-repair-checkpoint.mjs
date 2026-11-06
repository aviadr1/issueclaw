// Private, periodic checkpoints independent of the official Action's final outputs.
// Never upload Claude settings, authentication, environment files or whole checkouts.
import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';
import {Progress} from './briefing-progress.mjs';

const root = process.env.REPAIR_EVIDENCE;
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'manifest.json'), 'utf8'));
const transcript = path.join(root, 'sessions', `${manifest.session_id}.jsonl`);
fs.mkdirSync(path.dirname(transcript), {recursive: true});

if (process.argv[2] === 'hook') {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  if (input.session_id !== manifest.session_id) process.exit(0);
  if (input.transcript_path && fs.existsSync(input.transcript_path)) {
    fs.writeFileSync(path.join(root, 'transcript-path.txt'), input.transcript_path);
    fs.copyFileSync(input.transcript_path, transcript);
  }
} else {
  const {DefaultArtifactClient} = await import(pathToFileURL(path.join(process.env.REPAIR_NODE, 'node_modules/@actions/artifact/lib/artifact.js')).href);
  let sequence = 0;
  const snapshot = async () => {
    const pointer = path.join(root, 'transcript-path.txt');
    if (fs.existsSync(pointer)) {
      const source = fs.readFileSync(pointer, 'utf8');
      if (fs.existsSync(source)) fs.copyFileSync(source, transcript);
    }
    if (!fs.existsSync(transcript)) return;
    const progress = new Progress(Date.parse(manifest.created_at));
    let assistant = 0, user = 0;
    for (const line of fs.readFileSync(transcript, 'utf8').split('\n')) {
      try {
        const event = JSON.parse(line);
        progress.accept(event);
        if (event.type === 'assistant') assistant++;
        if (event.type === 'user') user++;
      } catch { /* The most recent transcript line can still be in flight. */ }
    }
    fs.writeFileSync(path.join(root, 'progress.json'), JSON.stringify({...progress.snapshot(),
      checkpoint_at: new Date().toISOString(), user_messages: user, assistant_messages: assistant,
      coverage: assistant ? 'Saved transcript through checkpoint; latest turn may be incomplete.' : 'Prompt only; no assistant response flushed yet.'}, null, 2));
    try {
      // Include new non-ignored source files; no commits or remote operations.
      execFileSync('git', ['-C', process.env.REPAIR_CHECKOUT, 'add', '-A']);
      const patch = execFileSync('git', ['-C', process.env.REPAIR_CHECKOUT, 'diff', '--cached', '--binary', manifest.sha], {maxBuffer: 10_000_000});
      fs.writeFileSync(path.join(root, 'candidate.patch'), patch);
    } catch (error) {
      fs.writeFileSync(path.join(root, 'patch-error.txt'), String(error.message).slice(0, 300));
    }
    const names = ['manifest.json', 'assignment.json', 'cohort.json', 'repair.prompt.md', 'repair.request.json',
      'progress.json', 'diagnosis.json', 'candidate.patch', 'usage.json', `sessions/${manifest.session_id}.jsonl`];
    const files = names.map(name => path.join(root, name)).filter(file => fs.existsSync(file));
    const result = await new DefaultArtifactClient().uploadArtifact(
      `repair-${manifest.incident_id}-checkpoint-${manifest.run_attempt}-${++sequence}`, files, root, {retentionDays: 30});
    fs.writeFileSync(path.join(root, 'latest-artifact.json'), JSON.stringify({id: result.id, checkpoint_at: new Date().toISOString()}));
  };
  // Each upload has a new immutable name: a cancellation cannot delete the previous copy.
  while (!fs.existsSync(path.join(root, 'stop-checkpoint'))) {
    try { await snapshot(); } catch (error) { console.error('Checkpoint upload failed:', error.message); }
    await new Promise(resolve => setTimeout(resolve, 60000));
  }
  await snapshot();
}
