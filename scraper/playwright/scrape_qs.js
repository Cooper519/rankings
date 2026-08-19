const { McpClient } = require("./mcp_client");
const fs = require("fs");
const OUT = "_qs_raw.json";
const t0 = Date.now();
const log = (...a) => console.log("[" + ((Date.now()-t0)/1000).toFixed(1) + "s]", ...a);

const FETCH_PAGE = async (page, ipp) => {
  const params = new URLSearchParams({
    nid: "4153156", page: String(page), items_per_page: String(ipp), tab: "indicators",
    region: "", countries: "", cities: "", search: "", star: "",
    sort_by: "", order_by: "", program_type: "", scholarship: ""
  });
  const r = await fetch("/rankings/endpoint?" + params.toString(), { credentials: "include" });
  if (!r.ok) throw new Error("HTTP " + r.status);
  const j = await r.json();
  const rows = j.score_nodes || [];
  return rows.map(x => ({
    name: (x.title || "").trim(),
    country: (x.country || "").trim(),
    rank: x.rank || x.rank_display || null,
    score: x.overall_score || null,
    region: x.region || ""
  })).filter(x => x.name && x.rank != null);
};

(async () => {
  const collected = [];
  const c = new McpClient({ headless: false });
  try {
    await c.init();
    log("navigate QS world rankings ...");
    await c.navigate("https://www.topuniversities.com/world-university-rankings");
    await c.waitFor(9);

    // attempt single big page
    log("fetch page=0 items_per_page=600 ...");
    let big = await c.eval(`async () => { try { return { r: await (${FETCH_PAGE.toString()})(0, 600) }; } catch(e){ return { e: e.message }; } }`);
    let obj = JSON.parse(big.replace(/^### Result\s*/, "").split(/\n### Ran Playwright/)[0]);
    if (obj.r && obj.r.length >= 500) {
      collected.push(...obj.r);
      log("big-page ok: +" + obj.r.length + " (total " + collected.length + ")");
    } else {
      log("big-page insufficient (" + (obj.r?obj.r.length:0) + ", err="+(obj.e||"") + "), paging 100s ...");
      for (let p = 0; p < 6 && collected.length < 500; p++) {
        const t = await c.eval(`async () => { try { return { r: await (${FETCH_PAGE.toString()})(${p}, 100) }; } catch(e){ return { e: e.message }; } }`);
        const o = JSON.parse(t.replace(/^### Result\s*/, "").split(/\n### Ran Playwright/)[0]);
        if (o.r) { collected.push(...o.r); log("p"+p+": +"+o.r.length+" (total "+collected.length+")"); }
        else log("p"+p+": ERR "+(o.e||""));
      }
    }

    fs.writeFileSync(OUT, JSON.stringify(collected), "utf8");
    log("DONE: " + collected.length + " rows -> " + OUT);
    if (collected[0]) log("#1 " + collected[0].rank + " " + collected[0].name + " " + collected[0].country);
    if (collected[499]) log("#500 " + collected[499].rank + " " + collected[499].name + " " + collected[499].country);
  } finally { await c.close(); }
})().catch(e => { console.error("FATAL", e.message); process.exit(1); });