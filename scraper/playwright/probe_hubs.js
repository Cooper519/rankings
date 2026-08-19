const { McpClient } = require("./mcp_client");
const fs = require("fs");
const HUBS = [
  { id: "u_eth_zurich", url: "https://ethz.ch/en/studies/master.html" },
  { id: "u_epfl", url: "https://www.epfl.ch/education/master/" },
  { id: "u_kth_royal_institute_of_technology", url: "https://www.kth.se/en/studies/master" },
  { id: "u_politecnico_di_milano", url: "https://www.polimi.it/en/international-prospective-students/laurea-magistrale-equals-to-master-of-science" },
  { id: "u_aalto_university", url: "https://www.aalto.fi/en/study-options" }
];
const t0 = Date.now();
const log = (...a) => console.log("[" + ((Date.now()-t0)/1000).toFixed(1) + "s]", ...a);
const parse = (t) => JSON.parse(t.replace(/^### Result\s*/, "").split(/\n### Ran Playwright/)[0]);
const LISTFN = `() => {
  const here = location.href.split("#")[0];
  const base = location.pathname.replace(/\\/$/, "");
  const out = [];
  const reList = /list of|all (master|programme)|programme list|master.s programmes|master.s programs|study programme|degree program|find a master|browse|programme overview|master programmes list/i;
  document.querySelectorAll("a[href]").forEach(a => {
    const h = (a.href||"").split("#")[0]; if (!h || h === here) return;
    const t = (a.innerText||a.textContent||"").replace(/\\s+/g," ").trim(); if (t.length<4) return;
    try { const u = new URL(h, location.href); if (u.host !== location.host) return; } catch(e){ return; }
    if (reList.test(t) || reList.test(h)) out.push({ t: t.slice(0,90), h });
  });
  const seen = new Set(); return out.filter(x => { if(seen.has(x.h)) return false; seen.add(x.h); return true; }).slice(0,12);
}`;
(async () => {
  const c = new McpClient({ headless: false });
  try {
    await c.init();
    for (const hub of HUBS) {
      log("=== " + hub.id + " :: " + hub.url);
      try {
        await c.navigate(hub.url); await c.waitFor(4);
        const t = await c.eval(LISTFN);
        const arr = parse(t) || [];
        log("  candidates: " + arr.length);
        arr.forEach(x => console.log("    " + x.h));
      } catch(e) { log("  err " + e.message); }
    }
  } finally { await c.close(); }
})().catch(e=>{console.error("FATAL",e.message);process.exit(1);});