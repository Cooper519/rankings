const { McpClient } = require("./mcp_client");
const t0 = Date.now();
const log = (...a) => console.log("[" + ((Date.now()-t0)/1000).toFixed(1) + "s]", ...a);
(async () => {
  const c = new McpClient({ headless: false });
  try {
    await c.init();
    await c.navigate("https://www.chalmers.se/en/education/find-masters-programme/");
    await c.waitFor(5);
    const t = await c.eval(`() => {
      const out = { title: document.title, aCount: document.querySelectorAll("a").length };
      const sample = [];
      document.querySelectorAll("a").forEach(a => {
        const tx = (a.innerText||"").trim(); const h = a.href||"";
        if (h && (tx.length>3) && /programme|program|msc|master|utbildning/i.test(tx+" "+h)) sample.push({t: tx.slice(0,80), h});
      });
      out.sample = sample.slice(0,30);
      // also try cards
      out.cards = document.querySelectorAll("[class*=programme],[class*=program],[class*=card]").length;
      out.bodyLen = (document.body.innerText||"").length;
      return out;
    }`);
    console.log(t.slice(0,2500));
  } finally { await c.close(); }
})().catch(e=>{console.error("FATAL",e.message);process.exit(1);});