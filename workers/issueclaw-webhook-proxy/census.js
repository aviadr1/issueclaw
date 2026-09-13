import { captureStatements, HOUR, nextHour } from "./store.js";
import { digest } from "./auth.js";

const SOURCES = {
  issues: "Issue",
  comments: "Comment",
  projects: "Project",
  documents: "Document",
  initiatives: "Initiative",
};
async function query(env, query, variables = {}) {
  const response = await fetch("https://api.linear.app/graphql", {
    method: "POST",
    headers: {
      Authorization: env.LINEAR_API_KEY,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ query, variables }),
    signal: AbortSignal.timeout(30000),
  });
  if (!response.ok) throw new Error(`Census HTTP ${response.status}`);
  const result = await response.json();
  if (result.errors?.length || !result.data)
    throw new Error("Census query failed");
  return result.data;
}

async function snapshot(env) {
  const identity = await query(env, "query { organization { id } }");
  if (identity.organization?.id !== env.INBOX_ORGANIZATION_ID)
    throw new Error("Census organization mismatch");
  const all = [];
  for (const [root, kind] of Object.entries(SOURCES)) {
    let after = null;
    const cursors = new Set();
    let total = 0;
    do {
      const data = await query(
        env,
        `query Census($after:String){ ${root}(first:100,after:$after,includeArchived:true){ nodes{id updatedAt ${kind === "Comment" ? "issue { id }" : ""}} pageInfo{hasNextPage endCursor} } }`,
        { after },
      );
      const page = data[root];
      if (
        !Array.isArray(page?.nodes) ||
        typeof page.pageInfo?.hasNextPage !== "boolean"
      )
        throw new Error("Incomplete census page");
      for (const node of page.nodes) {
        if (
          typeof node.id !== "string" ||
          !Number.isFinite(Date.parse(node.updatedAt))
        )
          throw new Error("Invalid census record");
        if (kind !== "Comment" || node.issue?.id) all.push({ kind, node });
      }
      total += page.nodes.length;
      if (total > 100000) throw new Error("Census capacity exceeded");
      if (!page.pageInfo.hasNextPage) break;
      after = page.pageInfo.endCursor;
      if (!after || cursors.has(after))
        throw new Error("Non-advancing census cursor");
      cursors.add(after);
    } while (true);
  }
  return all;
}

export async function reconcile(env, now = Date.now()) {
  const reservation = await env.INBOX.prepare(
    "UPDATE consumer SET next_census_at=? WHERE id=1 AND next_census_at<=?",
  )
    .bind(nextHour(now), now)
    .run();
  if (reservation.meta.changes !== 1) return;
  // Fetch EVERY page before inferring absence. This isn't a transactional
  // provider snapshot: two complete missing observations fence pagination churn.
  const rows = await snapshot(env);
  const existing = (await env.INBOX.prepare("SELECT * FROM census").all())
    .results;
  const old = new Map(existing.map((r) => [`${r.kind}/${r.id}`, r]));
  const seen = new Set(rows.map((r) => `${r.kind}/${r.node.id}`));
  const missing = existing.filter((r) => !seen.has(`${r.kind}/${r.id}`));
  if (missing.length >= 10 && missing.length > existing.length / 5)
    throw new Error("Census visibility drop; review required");
  const stamp = new Date(now).toISOString();
  let writes = [];
  async function enqueue(payload, metadata) {
    const raw = JSON.stringify(payload);
    writes.push(
      ...captureStatements(env, raw, await digest(raw), payload, now),
      metadata,
    );
    // Evidence, generation and observation move together in each D1 batch.
    if (writes.length >= ninetySix) {
      await env.INBOX.batch(writes);
      writes = [];
    }
  }
  for (const { kind, node } of rows) {
    const fingerprint = JSON.stringify([
      node.updatedAt,
      node.issue?.id || null,
    ]);
    const previous = old.get(`${kind}/${node.id}`);
    const payload = {
      organizationId: env.INBOX_ORGANIZATION_ID,
      type: kind,
      action: "update",
      data: { id: node.id, ...(node.issue ? { issueId: node.issue.id } : {}) },
      createdAt: stamp,
    };
    if (
      !previous ||
      previous.fingerprint !== fingerprint ||
      previous.missing_since !== null
    ) {
      await enqueue(
        payload,
        env.INBOX.prepare(
          "INSERT INTO census(kind,id,fingerprint,payload) VALUES(?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET fingerprint=excluded.fingerprint,payload=excluded.payload,missing_since=NULL",
        ).bind(kind, node.id, fingerprint, JSON.stringify(payload)),
      );
    }
  }
  for (const row of missing) {
    if (row.missing_since !== null && now - row.missing_since >= HOUR) {
      await enqueue(
        { ...JSON.parse(row.payload), action: "remove", createdAt: stamp },
        env.INBOX.prepare("DELETE FROM census WHERE kind=? AND id=?").bind(
          row.kind,
          row.id,
        ),
      );
    } else if (row.missing_since === null) {
      writes.push(
        env.INBOX.prepare(
          "UPDATE census SET missing_since=? WHERE kind=? AND id=? AND missing_since IS NULL",
        ).bind(now, row.kind, row.id),
      );
      if (writes.length >= ninetySix) {
        await env.INBOX.batch(writes);
        writes = [];
      }
    }
  }
  if (writes.length) await env.INBOX.batch(writes);
  await env.INBOX.prepare(
    "UPDATE consumer SET census_at=?,census_error=NULL WHERE id=1",
  )
    .bind(now)
    .run();
}

const ninetySix = 96; // Leave room for a complete three-statement entity transition.
