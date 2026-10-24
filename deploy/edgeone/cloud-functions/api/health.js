function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
      "X-Frame-Options": "DENY",
      "Referrer-Policy": "no-referrer"
    }
  });
}

export async function onRequestGet(context) {
  const env = context.env || process.env;
  const configured = {
    HEALTH_API_BASE_URL: Boolean(env.HEALTH_API_BASE_URL),
    EDGEONE_GATEWAY_SECRET: Boolean(env.EDGEONE_GATEWAY_SECRET)
  };
  if (!configured.HEALTH_API_BASE_URL || !configured.EDGEONE_GATEWAY_SECRET) {
    return json({ ok: false, runtime: "edgeone-gateway", configured }, 503);
  }
  try {
    const response = await fetch(`${String(env.HEALTH_API_BASE_URL).replace(/\/$/, "")}/health`, {
      headers: { "X-Gateway-Secret": env.EDGEONE_GATEWAY_SECRET },
      signal: AbortSignal.timeout(10_000)
    });
    const upstream = await response.json().catch(() => ({}));
    return json({
      ok: response.ok && upstream.ok === true,
      runtime: "edgeone-gateway",
      configured,
      upstream: {
        ok: upstream.ok === true,
        database: upstream.database || "unknown",
        worker: upstream.worker || "unknown"
      },
      checked_at: new Date().toISOString()
    }, response.ok && upstream.ok === true ? 200 : 503);
  } catch (error) {
    return json({
      ok: false,
      runtime: "edgeone-gateway",
      configured,
      upstream: { ok: false, error: error?.name || "UpstreamError" }
    }, 503);
  }
}
