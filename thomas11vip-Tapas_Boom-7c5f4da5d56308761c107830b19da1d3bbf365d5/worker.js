/**
 * Tapas Boom — Cloudflare Worker relay (30-second setup, free tier).
 *
 * Kyun: Heroku USA dyno ka IP kai Indian OTP services pe TCP-blocked
 * hai. CF Worker ka egress India-POP se hit karta hai, isliye
 * proxy service ke bina bhi bypass ho jaata hai.
 *
 * Setup:
 *   1. https://dash.cloudflare.com → Workers & Pages → Create Worker
 *   2. Iss file ka poora code paste karo, Deploy dabao.
 *   3. Deploy hone ke baad URL milega (e.g. https://tapas-relay.xyz.workers.dev)
 *   4. Heroku config vars me daalo:
 *        WORKER_RELAY_URL = https://tapas-relay.xyz.workers.dev
 *   5. Bot restart. Automatically first-priority relay ban jayega.
 *
 * Free tier: 100k req/day — bot ke liye kaafi.
 */
export default {
  async fetch(req) {
    const u = new URL(req.url);
    const target = u.searchParams.get("url");
    if (!target) return new Response("usage: /?url=<encoded-target>", { status: 400 });

    let dest;
    try { dest = new URL(target); }
    catch { return new Response("bad url", { status: 400 }); }

    // Forward incoming headers + body, strip hop-by-hop
    const drop = new Set(["host","cf-connecting-ip","cf-ipcountry","cf-ray",
      "cf-visitor","x-forwarded-for","x-forwarded-proto","x-real-ip"]);
    const h = new Headers();
    for (const [k, v] of req.headers) if (!drop.has(k.toLowerCase())) h.set(k, v);
    h.set("Host", dest.host);

    const init = {
      method: req.method,
      headers: h,
      redirect: "follow",
      body: ["GET","HEAD"].includes(req.method) ? undefined : await req.arrayBuffer(),
    };

    const r = await fetch(dest.toString(), init);
    const out = new Headers(r.headers);
    out.set("Access-Control-Allow-Origin", "*");
    return new Response(r.body, { status: r.status, headers: out });
  }
};
