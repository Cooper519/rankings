const { McpClient } = require("./mcp_client");
const fs = require("fs");
const EX = fs.readFileSync(__dirname + "/eval_extract.js", "utf8").trim();
const parse = (t) => JSON.parse(t.replace(/^### Result\s*/, "").split(/\n### Ran Playwright/)[0]);
(async () => {
  const c = new McpClient({ headless: false });
  try {
    await c.init();
    await c.navigate("https://www.chalmers.se/en/education/find-masters-programme/applied-mechanics-msc/");
    await c.waitFor(3);
    const t = await c.eval(EX);
    const o = parse(t);
    console.log("title:", o.title);
    console.log("deadlines:", JSON.stringify(o.deadlines));
    console.log("materials:", o.materials);
    console.log("ielts/toefl:", o.ielts, o.toefl);
  } finally { await c.close(); }
})().catch(e=>{console.error("FATAL",e.message);process.exit(1);});