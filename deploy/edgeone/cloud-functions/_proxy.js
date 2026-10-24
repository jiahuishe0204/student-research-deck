const REQUEST_HEADERS = ["content-type", "cookie", "x-csrf-token"];
const RESPONSE_HEADERS = ["content-type", "cache-control", "set-cookie"];

function json(payload, status) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" }
  });
}

function runtime(context) {
  return context.env || process.env;
}

function upstreamUrl(context) {
  const env = runtime(context);
  const base = String(env.CONTROL_API_BASE_URL || "").replace(/\/$/, "");
  if (!base || !env.EDGEONE_GATEWAY_SECRET) throw new Error("GatewayNotConfigured");
  const parsed = new URL(base);
  if (parsed.protocol !== "https:") throw new Error("GatewayOriginNotHttps");
  const incoming = new URL(context.request.url);
  return `${base}${incoming.pathname}${incoming.search}`;
}

export async function proxyControlApi(context) {
  const method = context.request.method.toUpperCase();
  if (!new Set(["GET", "POST"]).has(method)) return json({ ok: false, message: "请求方法不允许" }, 405);
  try {
    const env = runtime(context);
    const headers = new Headers();
    for (const name of REQUEST_HEADERS) {
      const value = context.request.headers.get(name);
      if (value) headers.set(name, value);
    }
    headers.set("X-Gateway-Secret", String(env.EDGEONE_GATEWAY_SECRET));
    headers.set("X-EdgeOne-Client-IP", String(context.clientIp || ""));
    const body = method === "GET" ? undefined : await context.request.arrayBuffer();
    const upstream = await fetch(upstreamUrl(context), {
      method,
      headers,
      body,
      redirect: "manual",
      signal: AbortSignal.timeout(15_000)
    });
    const responseHeaders = new Headers({
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
      "X-Frame-Options": "DENY",
      "Referrer-Policy": "no-referrer"
    });
    for (const name of RESPONSE_HEADERS) {
      const value = upstream.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
  } catch (error) {
    const unavailable = error?.message === "GatewayNotConfigured" || error?.message === "GatewayOriginNotHttps";
    return json({ ok: false, message: unavailable ? "生产网关尚未配置" : "生产服务暂时不可用" }, 503);
  }
}

