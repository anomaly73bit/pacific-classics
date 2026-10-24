// Pacific Classics — visit counter (Cloudflare Worker + D1)
//   POST /hit    {kind, ref?, title?, view?}  — sent by the public site (sendBeacon, text/plain)
//   GET  /stats?days=30                         — admin only (HTTP Basic, same credentials as the site admin)
// Stores no IP and no cookies: country/city come from Cloudflare, visitors are a daily-salted hash.

const BOT = /bot|crawl|spider|slurp|preview|monitor|headless|lighthouse|curl|wget|python|httpclient|facebookexternalhit|whatsapp/i;

function cors(req, env) {
  const origin = req.headers.get("Origin") || "";
  const ok = (env.ALLOWED_ORIGINS || "").split(",").map(s => s.trim()).includes(origin);
  return {
    "Access-Control-Allow-Origin": ok ? origin : "null",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
  };
}

const json = (obj, status, headers) =>
  new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json", ...headers } });

function pragueDay(ts) {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Prague", year: "numeric", month: "2-digit", day: "2-digit" }).format(ts);
}

async function sha256(s) {
  const b = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(b)].slice(0, 12).map(x => x.toString(16).padStart(2, "0")).join("");
}

function authorized(req, env) {
  const h = req.headers.get("Authorization") || "";
  if (!h.startsWith("Basic ") || !env.ADMIN_USER || !env.ADMIN_PASSWORD) return false;
  let dec = "";
  try { dec = atob(h.slice(6)); } catch (e) { return false; }
  const want = `${env.ADMIN_USER}:${env.ADMIN_PASSWORD}`;
  if (dec.length !== want.length) return false;
  let diff = 0;
  for (let i = 0; i < dec.length; i++) diff |= dec.charCodeAt(i) ^ want.charCodeAt(i);
  return diff === 0;
}

async function hit(req, env, h) {
  const ua = req.headers.get("User-Agent") || "";
  if (BOT.test(ua)) return new Response(null, { status: 204, headers: h });
  let b = {};
  try { b = JSON.parse(await req.text()); } catch (e) { return new Response(null, { status: 400, headers: h }); }
  const kind = ["page", "car", "quote"].includes(b.kind) ? b.kind : null;
  if (!kind) return new Response(null, { status: 400, headers: h });
  const ref = typeof b.ref === "string" && /^PC-[0-9A-F]{6}$/.test(b.ref) ? b.ref : null;
  const now = Date.now(), day = pragueDay(now);
  const cf = req.cf || {};
  const ip = req.headers.get("CF-Connecting-IP") || "";
  const visitor = await sha256(`${ip}|${ua}|${day}|${env.SALT || "pc"}`);
  let referrer = null;
  try { const r = new URL(b.referrer || ""); if (!/pacificit\.solutions|github\.io/.test(r.host)) referrer = r.host.replace(/^www\./, ""); } catch (e) {}
  await env.DB.prepare(
    "INSERT INTO hits (ts, day, kind, ref, title, view, country, city, lat, lon, visitor, referrer, device) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
  ).bind(now, day, kind, ref, (b.title || "").slice(0, 140) || null, (b.view || "").slice(0, 20) || null,
         cf.country || null, cf.city || null,
         cf.latitude ? Math.round(parseFloat(cf.latitude) * 10) / 10 : null,
         cf.longitude ? Math.round(parseFloat(cf.longitude) * 10) / 10 : null,
         visitor, referrer, /Mobi|Android|iPhone/i.test(ua) ? "mobile" : "desktop").run();
  return new Response(null, { status: 204, headers: h });
}

async function stats(req, env, h) {
  if (!authorized(req, env)) return json({ error: "unauthorized" }, 401, h);
  const url = new URL(req.url);
  const days = Math.min(400, Math.max(1, parseInt(url.searchParams.get("days") || "30", 10)));
  const from = pragueDay(Date.now() - (days - 1) * 86400000);
  const q = (sql, ...args) => env.DB.prepare(sql).bind(from, ...args).all().then(r => r.results);
  const [daily, countries, places, cars, refs, devices, totals, monthly] = await Promise.all([
    q(`SELECT day, SUM(kind='page') views, COUNT(DISTINCT visitor) visitors, SUM(kind='car') car_views, SUM(kind='quote') quotes
       FROM hits WHERE day >= ? GROUP BY day ORDER BY day`),
    q(`SELECT country, COUNT(DISTINCT visitor) visitors, SUM(kind='page') views FROM hits
       WHERE day >= ? AND country IS NOT NULL GROUP BY country ORDER BY visitors DESC`),
    q(`SELECT city, country, lat, lon, COUNT(DISTINCT visitor) visitors FROM hits
       WHERE day >= ? AND lat IS NOT NULL GROUP BY lat, lon ORDER BY visitors DESC LIMIT 500`),
    q(`SELECT ref, MAX(title) title, COUNT(*) views, COUNT(DISTINCT visitor) visitors, SUM(kind='quote') quotes FROM hits
       WHERE day >= ? AND ref IS NOT NULL AND kind IN ('car','quote') GROUP BY ref ORDER BY views DESC LIMIT 50`),
    q(`SELECT COALESCE(referrer, '(diretto)') referrer, COUNT(DISTINCT visitor) visitors FROM hits
       WHERE day >= ? AND kind='page' GROUP BY referrer ORDER BY visitors DESC LIMIT 20`),
    q(`SELECT device, COUNT(DISTINCT visitor) visitors FROM hits WHERE day >= ? GROUP BY device`),
    q(`SELECT SUM(kind='page') views, COUNT(DISTINCT visitor || day) visitors, SUM(kind='car') car_views, SUM(kind='quote') quotes
       FROM hits WHERE day >= ?`),
    q(`SELECT substr(day,1,7) month, SUM(kind='page') views, COUNT(DISTINCT visitor || day) visitors FROM hits
       WHERE day >= ? GROUP BY month ORDER BY month`),
  ]);
  return json({ from, days, totals: totals[0], daily, monthly, countries, places, cars, referrers: refs, devices }, 200,
              { ...h, "Cache-Control": "no-store" });
}

export default {
  async fetch(req, env) {
    const h = cors(req, env);
    const { pathname } = new URL(req.url);
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: h });
    try {
      if (pathname === "/hit" && req.method === "POST") return await hit(req, env, h);
      if (pathname === "/stats" && req.method === "GET") return await stats(req, env, h);
      return json({ ok: true, service: "pacific-classics-stats" }, 200, h);
    } catch (e) {
      return json({ error: String(e).slice(0, 200) }, 500, h);
    }
  },
  async scheduled(event, env) {
    const keep = parseInt(env.RETENTION_DAYS || "400", 10);
    await env.DB.prepare("DELETE FROM hits WHERE ts < ?").bind(Date.now() - keep * 86400000).run();
  },
};
