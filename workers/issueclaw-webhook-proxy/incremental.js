import { digest } from "./auth.js";
import { aggregate, captureStatements, commentParent } from "./store.js";

// Bounded authenticated imports; share the webhook's atomic capture operation.
export async function importMetadata(env, body) {
  let records;
  try {
    if (body.organizationId !== env.INBOX_ORGANIZATION_ID ||
        !Array.isArray(body.records) || !body.records.length || body.records.length > 25)
      throw new Error("Invalid batch");
    records = body.records.map((record) => {
      if (record.organizationId !== env.INBOX_ORGANIZATION_ID || record.action !== "update" ||
          typeof record.data?.id !== "string" || !record.data.id ||
          typeof record.data.updatedAt !== "string" ||
          !Number.isFinite(Date.parse(record.data.updatedAt))) throw new Error("Invalid metadata");
      // Normalize timestamps and fields, so retries use the same digest.
      const updatedAt = new Date(record.data.updatedAt).toISOString();
      const owner = record.type === "Comment" ? commentParent(record.data) : null;
      const value = { organizationId: body.organizationId, type: record.type, action: "update",
        data: { id: record.data.id, updatedAt,
          ...(owner ? { [owner.field]: owner.id } : {}),
          ...(record.type === "ProjectUpdate" ? { projectId: record.data.projectId } : {}) },
        createdAt: updatedAt };
      aggregate(value, env.INBOX_ORGANIZATION_ID);
      return value;
    });
  } catch {
    return new Response("Invalid metadata batch", { status: 400 });
  }
  await env.INBOX.batch(await metadataStatements(env, records));
  return Response.json({ accepted: records.length });
}

// Called only after whole-request validation. Source observations remain
// distinct, but each mirrored owner needs just one dirty generation per batch.
export async function metadataStatements(env, records, now = Date.now()) {
  const groups = new Map();
  for (const record of records) {
    const key = aggregate(record, env.INBOX_ORGANIZATION_ID).key;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(record);
  }
  const statements = [];
  for (const sources of groups.values()) {
    sources.sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
    const newest = sources.reduce((a, b) => Date.parse(a.createdAt) >= Date.parse(b.createdAt) ? a : b);
    const raw = JSON.stringify({ ...newest, metadataSources: sources });
    statements.push(...captureStatements(env, raw, await digest("metadata:" + raw), newest, now, true, sources));
  }
  return statements;
}

export async function completeReconciliation(env, body) {
  const { expected, until } = body;
  if (!Number.isSafeInteger(expected) || expected < 0 || !Number.isSafeInteger(until) ||
      until <= expected || until > Date.now())
    return new Response("Invalid watermark", { status: 400 });
  const result = await env.INBOX.prepare(
    "UPDATE consumer SET reconciliation_at=? WHERE id=1 AND reconciliation_at=?",
  ).bind(until, expected).run();
  return new Response(result.meta.changes === 1 ? "Completed" : "Stale watermark",
    { status: result.meta.changes === 1 ? 200 : 409 });
}
