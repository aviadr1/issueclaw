import assert from "node:assert/strict";
import { test } from "node:test";
import { harness, event } from "./harness.js";

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
