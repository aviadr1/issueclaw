import assert from "node:assert/strict";
import { test } from "node:test";
import { harness } from "./harness.js";

test("unchanged complete census does not create more work or rewrite metadata", async (t) => {
  const s = source();
  s.rows.issues = [{ id: "one", updatedAt: "2026-09-13T00:00:00Z" }];
  const h = await harness(t, {
    linear: (b) => s.handle(b),
    dispatchStatus: 204,
  });
  const worker = await h.mf.getWorker();
  await worker.scheduled({ cron: "17 * * * *" });
  await h.ack(await (await h.api("claim")).json());
  const before = await h.db.prepare("SELECT * FROM census").all();
  await h.db
    .prepare("UPDATE consumer SET next_census_at=0,next_wakeup_at=0")
    .run();
  await worker.scheduled({ cron: "17 * * * *" });
  assert.deepEqual(
    (await h.db.prepare("SELECT * FROM census").all()).results,
    before.results,
  );
  assert.equal((await h.api("claim")).status, 204);
  assert.equal(h.calls.length, 1);
});

function source() {
  const rows = {
    issues: [],
    comments: [],
    projects: [],
    initiatives: [],
    documents: [],
  };
  let broken = false;
  return {
    rows,
    break() {
      broken = true;
    },
    handle({ query, variables }) {
      if (broken) return { errors: [{ message: "Forbidden" }] };
      if (query.includes("organization {"))
        return { data: { organization: { id: "test-org" } } };
      const kind = Object.keys(rows).find((k) => query.includes(`${k}(`));
      const start = Number(variables.after || 0),
        nodes = rows[kind].slice(start, start + 1);
      return {
        data: {
          [kind]: {
            nodes,
            pageInfo: {
              hasNextPage: start + 1 < rows[kind].length,
              endCursor: String(start + 1),
            },
          },
        },
      };
    },
  };
}

test("hourly metadata census recovers a suppressed webhook, including a later page", async (t) => {
  const s = source();
  s.rows.issues = [
    { id: "one", updatedAt: "2026-09-13T00:00:00Z" },
    { id: "two", updatedAt: "2026-09-13T00:00:00Z" },
  ];
  const h = await harness(t, {
    linear: (b) => s.handle(b),
    dispatchStatus: 204,
  });
  await (await h.mf.getWorker()).scheduled({ cron: "17 * * * *" });
  const batch = await (await h.api("claim")).json();
  assert.deepEqual(batch.items.map((i) => i.payload.data.id).sort(), [
    "one",
    "two",
  ]);
  assert.equal(h.calls.length, 1);
});

test("comment edit and deletion dirty its parent without relying on issue updatedAt", async (t) => {
  const s = source();
  s.rows.comments = [
    {
      id: "comment",
      updatedAt: "2026-09-13T00:00:00Z",
      issue: { id: "parent" },
    },
  ];
  const h = await harness(t, { linear: (b) => s.handle(b) });
  const worker = await h.mf.getWorker();
  await worker.scheduled({ cron: "17 * * * *" });
  await h.ack(await (await h.api("claim")).json());
  s.rows.comments = [];
  await h.db.prepare("UPDATE consumer SET next_census_at=0").run();
  await worker.scheduled({ cron: "17 * * * *" });
  // Absence requires two completed observations, not one partial page.
  assert.equal((await h.api("claim")).status, 204);
  // Duplicate delivery of the same cron must not confirm deletion.
  await worker.scheduled({ cron: "17 * * * *" });
  assert.equal((await h.api("claim")).status, 204);
  await h.db.prepare("UPDATE consumer SET next_census_at=0").run();
  await h.db
    .prepare("UPDATE census SET missing_since=missing_since-3600001")
    .run();
  await worker.scheduled({ cron: "17 * * * *" });
  const batch = await (await h.api("claim")).json();
  assert.equal(batch.items[0].payload.type, "Issue");
  assert.equal(batch.items[0].payload.data.id, "parent");
  assert.equal(batch.items[0].payload.action, "update");
});

test("failed census cannot infer deletions or erase its last successful snapshot", async (t) => {
  const s = source();
  s.rows.documents = [{ id: "doc", updatedAt: "2026-09-13T00:00:00Z" }];
  const h = await harness(t, { linear: (b) => s.handle(b) });
  const worker = await h.mf.getWorker();
  await worker.scheduled({ cron: "17 * * * *" });
  await h.ack(await (await h.api("claim")).json());
  s.break();
  await h.db.prepare("UPDATE consumer SET next_census_at=0").run();
  await worker.scheduled({ cron: "17 * * * *" });
  await worker.scheduled({ cron: "17 * * * *" });
  assert.equal((await h.api("claim")).status, 204);
  assert.equal(
    (await h.db.prepare("SELECT count(*) AS n FROM census").first()).n,
    1,
  );
  assert.ok((await (await h.api("status")).json()).census_error);
});
