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
  const statements = [];
  for (const record of records) {
    const raw = JSON.stringify(record);
    statements.push(...captureStatements(env, raw, await digest("metadata:" + raw), record, Date.now(), true));
  }
  await env.INBOX.batch(statements);
  return Response.json({ accepted: records.length });
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
