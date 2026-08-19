const { McpClient } = require("./mcp_client");
const fs = require("fs");
const SE = fs.readFileSync(__dirname + "/eval_bing.js", "utf8").trim();
const parse = (t) => JSON.parse(t.replace(/^### Result\s*/, "").split(/\n### Ran Playwright/)[0]);
const q = (s) => encodeURIComponent(s);
(async () => {
  const c = new McpClient({ headless: false });
  try {
    await c.init();
    for (const name of ["RWTH Aachen University", "University of Vienna", "Aalborg University"]) {
      const url = "https://www.bing.com/search?q=" + q(name + " master programmes english admission");
      console.log("=== " + name);
      try {
        await c.navigate(url); await c.waitFor(3);
        const t = await c.eval(SE);
        const o = parse(t);
        console.log("  count=" + o.count + " title=" + o.title);
        (o.sample||[]).slice(0,5).forEach(x => console.log("   " + x.href + "  ::  " + x.title.slice(0,70)));
      } catch(e) { console.log("  err " + e.message); }
    }
  } finally { await c.close(); }
})().catch(e=>{console.error("FATAL",e.message);process.exit(1);});