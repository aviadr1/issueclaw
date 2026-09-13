// Only fixed categories leave this boundary. D1 errors can contain SQL or
// private source values, so never log/return their messages or stack traces.
export function failureResponse(error, now = Date.now()) {
  let code = "inbox_unavailable";
  let cause = error;
  for (let depth = 0; cause && depth < 4; depth++, cause = cause.cause) {
    const message = typeof cause.message === "string" ? cause.message : "";
    for (const kind of ["read", "write"]) {
      if (message.includes(`account has exceeded D1's free tier daily row ${kind} limit`)) {
        code = `d1_daily_${kind}_limit`;
      }
    }
  }
  const day = 86400000;
  const retrySeconds = code === "inbox_unavailable" ? 60 :
    Math.max(1, Math.ceil((day - now % day) / 1000));
  console.error(JSON.stringify({ event: "inbox_operation_failed", code }));
  return Response.json({ error: code }, {
    status: 503, headers: { "Retry-After": String(retrySeconds) },
  });
}
