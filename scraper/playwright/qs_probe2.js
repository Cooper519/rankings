const { McpClient } = require("./mcp_client");
const fs = require("fs");
const t0 = Date.now();
const log = (...a) => console.log("[" + ((Date.now()-t0)/1000).toFixed(1) + "s]", ...a);

(async () => {
  const c = new McpClient({ headless: false });
  try {
    await c.init();
    log("navigate QS world rankings ...");
    await c.navigate("https://www.topuniversities.com/world-university-rankings");
    await c.waitFor(9);
    const probe = await c.eval(`async () => {
      const params = new URLSearchParams({
        nid: "4153156", page: "0", items_per_page: "5", tab: "indicators",
        region: "", countries: "", cities: "", search: "", star: "",
        sort_by: "", order_by: "", program_type: "", scholarship: ""
      });
      try {
        const r = await fetch("/rankings/endpoint?" + params.toString(), { credentials: "include" });
        const j = await r.json();
        const rows = j.score_nodes || [];
        return { ok:true, status:r.status, total: j.total_record, pages: j.total_pages,
                 rowsLen: rows.length, row0Keys: rows[0]?Object.keys(rows[0]):[],
                 row0: rows[0] };
      } catch (e) { return { ok:false, msg:e.message }; }
    }`);
    fs.writeFileSync("_qs_probe.json", probe.replace(/^### Result\s*/, "").split(/\n### Ran Playwright/)[0], "utf8");
    log("probe:"); console.log(probe.slice(0, 3000));
  } finally { await c.close(); }
})().catch(e => { console.error("FATAL", e.message); process.exit(1); });