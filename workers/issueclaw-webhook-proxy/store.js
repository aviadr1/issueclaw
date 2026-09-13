export const HOUR = 60 * 60 * 1000;
export const LEASE_MS = 10 * 60 * 1000; // Longer than the caller's five-minute job.
export const BATCH_SIZE = 100;
// Use clock slots, not completion + 1h: cron jitter must not skip an hour.
export const nextHour = (now) => (Math.floor(now / HOUR) + 1) * HOUR;

export function commentParent(data) {
  for (const [field,type] of [["issueId","Issue"],["projectId","Project"],["initiativeId","Initiative"],["documentId","Document"]]) {
    if (typeof data?.[field] === "string" && data[field]) return {field,type,id:data[field]};
  }
  throw new Error("Unsupported comment parent");
}

export function aggregate(payload, organization) {
  if (payload.organizationId !== organization)
    throw new Error("Wrong organization");
  let type = payload.type,
    id = payload.data?.id,
    action = payload.action;
  if (type === "Comment") {
    const owner = commentParent(payload.data);
    id = owner.id;
    type = owner.type;
    action = "update";
  }
  if (type === "ProjectUpdate") {
    id = payload.data.projectId;
    if (!id) throw new Error("Unsupported project update parent");
    type = "Project";
    action = "update";
  }
  if (
    !["Issue", "Project", "Initiative", "Document"].includes(type) ||
    typeof id !== "string" ||
    !id ||
    !["create", "update", "remove"].includes(action)
  )
    throw new Error("Unsupported event");
  const sourceTime = Date.parse(payload.createdAt);
  if (!Number.isFinite(sourceTime)) throw new Error("Invalid event time");
  return {
    key: `${organization}/${type}/${id}`,
    sourceTime,
    payload: { type, action, data: { id }, createdAt: payload.createdAt },
  };
}

export function captureStatements(env, raw, digest, payload, now = Date.now(), metadata = false) {
  const item = aggregate(payload, env.INBOX_ORGANIZATION_ID);
  const version = Date.parse(payload.data?.updatedAt);
  const observed = Number.isFinite(version) && typeof payload.data.id === "string";
  // Evidence and dirty generation commit together. Retry deduplication uses the
  // retained digest; later edits preserve the oldest unacknowledged timestamp.
  const statements = [
    metadata ? env.INBOX.prepare(
      `INSERT INTO events(digest,work_key,payload,received_at)
       SELECT ?,?,?,? WHERE NOT EXISTS(SELECT 1 FROM source_versions
       WHERE kind=? AND id=? AND parent_key=? AND source_time>=?)
       ON CONFLICT(digest) DO NOTHING`,
    ).bind(digest,item.key,raw,now,payload.type,payload.data.id,item.key,version)
    : env.INBOX.prepare(
      // DO NOTHING still advances SQLite's AUTOINCREMENT sequence on conflict.
      // Avoid attempting the insert for a known digest, inside the same batch.
      `INSERT INTO events(digest, work_key, payload, received_at)
       SELECT ?,?,?,? WHERE NOT EXISTS(SELECT 1 FROM events WHERE digest=?)
       ON CONFLICT(digest) DO NOTHING`,
    ).bind(digest, item.key, raw, now, digest),
    env.INBOX.prepare(
      `INSERT INTO work(key,generation,payload,source_time,first_pending_at)
      SELECT work_key,seq,?,?,? FROM events WHERE digest=?
      ON CONFLICT(key) DO UPDATE SET
        generation=excluded.generation,
        payload=CASE WHEN excluded.source_time >= work.source_time THEN excluded.payload ELSE work.payload END,
        source_time=MAX(work.source_time,excluded.source_time),
        first_pending_at=CASE WHEN work.generation <= work.acked_generation THEN excluded.first_pending_at ELSE work.first_pending_at END
      WHERE excluded.generation > work.generation`,
    ).bind(JSON.stringify(item.payload), item.sourceTime, now, digest),
  ];
  if (observed) statements.push(env.INBOX.prepare(
    `INSERT INTO source_versions(kind,id,parent_key,source_time) VALUES(?,?,?,?)
     ON CONFLICT(kind,id) DO UPDATE SET parent_key=excluded.parent_key,source_time=excluded.source_time
     WHERE excluded.source_time>source_versions.source_time
       OR (excluded.source_time=source_versions.source_time AND excluded.parent_key!=source_versions.parent_key)`,
  ).bind(payload.type,payload.data.id,item.key,version));
  return statements;
}

export async function capture(env, raw, digest, payload, now = Date.now()) {
  await env.INBOX.batch(captureStatements(env, raw, digest, payload, now));
}

export async function claim(env, now = Date.now()) {
  const token = crypto.randomUUID();
  const result = await env.INBOX.batch([
    env.INBOX.prepare(
      `UPDATE work SET token=?, lease_until=?, lease_generation=generation, lease_payload=payload
      WHERE key IN (SELECT key FROM work WHERE generation>acked_generation AND lease_until<=? AND retry_at<=?
      ORDER BY first_pending_at,key LIMIT ?)`,
    ).bind(token, now + LEASE_MS, now, now, BATCH_SIZE),
    env.INBOX.prepare(
      "SELECT key,lease_generation AS generation,lease_payload AS payload FROM work WHERE token=? ORDER BY key",
    ).bind(token),
  ]);
  const items = result[1].results.map((i) => ({
    ...i,
    payload: JSON.parse(i.payload),
  }));
  return items.length
    ? Response.json({ stream: env.INBOX_STREAM, token, items })
    : new Response(null, { status: 204 });
}

export async function acknowledge(env, body, now = Date.now()) {
  const { token, results } = body;
  if (
    typeof token !== "string" ||
    !Array.isArray(results) ||
    !results.length ||
    results.length > BATCH_SIZE ||
    results.some(
      (r) => !r || typeof r.key !== "string" || typeof r.success !== "boolean" ||
        (r.deferred !== undefined && typeof r.deferred !== "boolean") ||
        (r.success && r.deferred),
    ) ||
    new Set(results.map((r) => r.key)).size !== results.length
  )
    return new Response("Invalid acknowledgement", { status: 400 });
  // Deferral releases ownership without claiming publication or inventing a
  // failure. Preserve prior failures and pending age; only success clears them.
  const replies = await env.INBOX.batch(
    results.map((r) =>
      env.INBOX.prepare(
        `UPDATE work SET
    acked_generation=CASE WHEN ? THEN lease_generation ELSE acked_generation END,
    first_pending_at=CASE WHEN ? AND generation=lease_generation THEN NULL ELSE first_pending_at END,
    failures=CASE WHEN ? THEN 0 WHEN ? THEN failures ELSE failures+1 END,
    retry_at=CASE WHEN ? THEN 0 ELSE ? END,
    token=NULL, lease_until=0
    WHERE key=? AND token=? AND lease_until>?`,
      ).bind(
        r.success,
        r.success,
        r.success,
        r.deferred === true,
        r.success || r.deferred === true,
        nextHour(now),
        r.key,
        token,
        now,
      ),
    ),
  );
  // An expired owner cannot ACK a new generation. Partial successful ACKs are
  // safe on retry because Git receipts remain the processing authority.
  return new Response(
    replies.every((r) => r.meta.changes === 1) ? "Acknowledged" : "Stale lease",
    { status: replies.every((r) => r.meta.changes === 1) ? 200 : 409 },
  );
}

export async function status(env, now = Date.now()) {
  const row = await env.INBOX.prepare(
    "SELECT count(*) AS pending,min(first_pending_at) AS oldest_pending_at,COALESCE(sum(failures>0),0) AS failed FROM work WHERE generation>acked_generation",
  ).first();
  const census = await env.INBOX.prepare(
    "SELECT reconciliation_at FROM consumer WHERE id=1",
  ).first();
  return {
    ...row,
    ...census,
    organization_id: env.INBOX_ORGANIZATION_ID,
    stream: env.INBOX_STREAM,
    reconciliation_stale: !census.reconciliation_at || now - census.reconciliation_at > 48 * HOUR,
    oldest_pending_age_ms:
      row.oldest_pending_at === null ? 0 : now - row.oldest_pending_at,
    freshness_breached:
      row.oldest_pending_at !== null && now - row.oldest_pending_at > 2 * HOUR,
  };
}

export async function reserveDispatch(env, now = Date.now()) {
  const result = await env.INBOX.prepare(
    `UPDATE consumer SET next_wakeup_at=? WHERE id=1 AND next_wakeup_at<=?
    AND EXISTS(SELECT key FROM work WHERE generation>acked_generation AND lease_until<=? AND retry_at<=?)`,
  )
    .bind(nextHour(now), now, now, now)
    .run();
  return result.meta.changes === 1;
}

export async function retain(env, now = Date.now()) {
  // Keep digests for retry deduplication; strip only processed payload bodies.
  await env.INBOX.prepare(
    `UPDATE events SET payload='' WHERE received_at<? AND payload!=''
    AND seq <= COALESCE((SELECT acked_generation FROM work WHERE key=events.work_key),0)`,
  )
    .bind(now - 30 * 24 * HOUR)
    .run();
}
