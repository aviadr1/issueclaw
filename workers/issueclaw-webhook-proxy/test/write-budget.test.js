import assert from "node:assert/strict";
import { test } from "node:test";
import { harness, event } from "./harness.js";
import { captureStatements } from "../store.js";
import { digest } from "../auth.js";

for (const mode of ["webhook", "metadata"]) {
  test(`${mode} duplicate is storage-idempotent, not just output-idempotent`, async (t) => {
    const h = await harness(t);
    const record = event("one", { data: { id: "one", updatedAt: "2026-09-13T00:00:00Z" } });
    const send = () => mode === "webhook" ? h.send(record) :
      h.api("reconcile", { organizationId: "test-org", records: [record] });
    assert.equal((await send()).status, 200);
    const first = await (await h.api("claim")).json();
    await h.ack(first);
    // Instrument writes at the real database boundary; do not mock capture.
    await h.db.exec("CREATE TABLE audit(n INTEGER); CREATE TRIGGER version_write AFTER UPDATE ON source_versions BEGIN INSERT INTO audit VALUES(1); END;");
    const sequence = await h.db.prepare("SELECT seq FROM sqlite_sequence WHERE name='events'").first();
    for (let i = 0; i < 3; i++) assert.equal((await send()).status, 200);
    assert.deepEqual(await h.db.prepare("SELECT seq FROM sqlite_sequence WHERE name='events'").first(), sequence);
    assert.equal((await h.db.prepare("SELECT count(*) n FROM audit").first()).n, 0);
    assert.equal((await h.api("claim")).status, 204);
    record.createdAt = record.data.updatedAt = "2026-09-13T01:00:00Z";
    assert.equal((await send()).status, 200);
    const next = await (await h.api("claim")).json();
    assert.ok(next.items[0].generation > first.items[0].generation);
  });
}

test("capture row-write budget is measured through the production SQL", async (t) => {
  const h = await harness(t);
  const record = event("budget", { data: { id: "budget", updatedAt: "2026-09-13T00:00:00Z" } });
  const raw = JSON.stringify(record);
  const env = { INBOX: h.db, INBOX_ORGANIZATION_ID: "test-org" };
  const results = await h.db.batch(captureStatements(env, raw, await digest(raw), record));
  assert.equal(results.reduce((n, r) => n + r.meta.changes, 0), 3);
  assert.ok(results.reduce((n, r) => n + r.meta.rows_written, 0) <= 9,
    "One new source observation must not maintain unused event indexes");
  const repeated = await h.db.batch(captureStatements(env, raw, await digest(raw), record));
  assert.equal(repeated.reduce((n, r) => n + r.meta.rows_written, 0), 0);
});

for (const mode of ["webhook", "metadata"]) {
  for (const table of ["work", "source_versions"]) {
   for (const compatibilityDate of ["2026-07-01", "2026-09-13"]) {
    test(`${mode}: ${table} failure rolls back capture and exact retry recovers (${compatibilityDate})`, async (t) => {
      const h = await harness(t, { compatibilityDate });
      const record = event("recover", { data: { id: "recover", updatedAt: "2026-09-13T00:00:00Z" } });
      const send = () => mode === "webhook" ? h.send(record) :
        h.api("reconcile", { organizationId: "test-org", records: [record] });
      await h.db.exec(`CREATE TRIGGER outage BEFORE INSERT ON ${table} BEGIN SELECT RAISE(ABORT, 'storage unavailable'); END;`);
      assert.equal((await send()).status, 503);
      for (const name of ["events", "work", "source_versions"])
        assert.equal((await h.db.prepare(`SELECT count(*) n FROM ${name}`).first()).n, 0);
      await h.db.exec("DROP TRIGGER outage");
      assert.equal((await send()).status, 200);
      const first = await (await h.api("claim")).json();
      record.createdAt = record.data.updatedAt = "2026-09-13T01:00:00Z";
      assert.equal((await send()).status, 200);
      await h.ack(first);
      const next = await (await h.api("claim")).json();
      assert.ok(next.items[0].generation > first.items[0].generation);
      await h.ack(next);
      assert.equal((await (await h.api("status")).json()).pending, 0);
    });
   }
  }
}
