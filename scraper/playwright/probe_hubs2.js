const { McpClient } = require("./mcp_client");
const t0 = Date.now();
const log = (...a) => console.log("[" + ((Date.now()-t0)/1000).toFixed(1) + "s]", ...a);
const parse = (t) => JSON.parse(t.replace(/^### Result\s*/, "").split(/\n### Ran Playwright/)[0]);
const FN = (base) => `() => {
  const here = location.href.split("#")[0];
  const b = ${JSON.stringify(base)};
  const out = [];
  document.querySelectorAll("a[href]").forEach(a => {
    const h = (a.href||"").split("#")[0]; if (!h || h === here) return;
    const t = (a.innerText||a.textContent||"").replace(/\\s+/g," ").trim(); if (!t) return;
    try { const u = new URL(h, location.href); if (u.host !== location.host) return;
      const p = u.pathname.replace(/\\/$/, "");
      if (b && !p.startsWith(b + "/")) return;
      if (p === (b||"").replace(/\\/$/, "")) return;
    } catch(e){ return; }
    out.push({ t: t.slice(0,80), h });
  });
  const seen = new Set(); return out.filter(x=>{ if(seen.has(x.h))return false; seen.add(x.h); return true; }).slice(0,25);
}`;
(async () => {
  const c = new McpClient({ headless: false });
  try {
    await c.init();
    // PoliMi: find programme list link
    log("=== PoliMi hub ===");
    await c.navigate("https://www.polimi.it/en/international-prospective-students/laurea-magistrale-equals-to-master-of-science");
    await c.waitFor(4);
    let t = await c.eval(`() => {
      const out=[];
      document.querySelectorAll("a[href]").forEach(a=>{
        const h=(a.href||"").split("#")[0]; const tx=(a.innerText||"").replace(/\\s+/g," ").trim();
        if (!h||!tx) return;
        if (/programme|program|master|msc|laurea/i.test(tx+" "+h)) out.push({t:tx.slice(0,80),h});
      });
      const s=new Set(); return out.filter(x=>{if(s.has(x.h))return false;s.add(x.h);return true;}).slice(0,20);
    }`);
    parse(t).forEach(x=>console.log("   " + x.h + "  ::  " + x.t));
    // Aalto study-options sub-paths
    log("=== Aalto study-options sub-paths ===");
    await c.navigate("https://www.aalto.fi/en/study-options");
    await c.waitFor(6);
    t = await c.eval(FN("/en/study-options"));
    const arr = parse(t) || [];
    log("  sub-path links: " + arr.length);
    arr.slice(0,15).forEach(x=>console.log("   " + x.h + "  ::  " + x.t));
  } finally { await c.close(); }
})().catch(e=>{console.error("FATAL",e.message);process.exit(1);});