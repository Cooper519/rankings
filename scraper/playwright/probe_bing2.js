const { McpClient } = require("./mcp_client");
const fs = require("fs");
const SE = fs.readFileSync(__dirname + "/eval_bing.js", "utf8").trim();
const parse = (t) => JSON.parse(t.replace(/^### Result\s*/, "").split(/\n### Ran Playwright/)[0]);
(async () => {
  const c = new McpClient({ headless: false });
  try {
    await c.init();
    await c.navigate("https://www.bing.com/search?q=" + encodeURIComponent("RWTH Aachen University master programmes english"));
    await c.waitFor(3);
    const o = parse(await c.eval(SE));
    console.log("count=" + o.count);
    o.sample.slice(0,6).forEach(x => console.log("  " + x.host + "  ::  " + x.title.slice(0,60) + "  ::  " + x.href));
  } finally { await c.close(); }
})().catch(e=>{console.error("FATAL",e.message);process.exit(1);});