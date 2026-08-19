const { McpClient } = require("./mcp_client");
const fs = require("fs");

const TARGET_FILE = process.argv[2] || "discovery_targets.json";
const WAIT = Number(process.argv[3] || 3);
const DISCOVER = fs.readFileSync(__dirname + "/eval_discover.js", "utf8").trim();
const parse = (text) => JSON.parse(text.replace(/^### Result\s*/, "").split(/\n### Ran Playwright/)[0]);

const targets = JSON.parse(fs.readFileSync(__dirname + "/" + TARGET_FILE, "utf8"));

(async () => {
  const client = new McpClient({ headless: true });
  try {
    await client.init();
    for (const target of targets) {
      try {
        await client.navigate(target.url);
        await client.waitFor(target.wait || WAIT);
        try {
          await client.eval("async () => { for (let i=0;i<4;i++){ window.scrollTo(0, document.body.scrollHeight); await new Promise(r=>setTimeout(r,350)); } window.scrollTo(0,0); return document.links.length; }");
        } catch (e) {}
        const links = parse(await client.eval(DISCOVER)) || [];
        console.log(JSON.stringify({ label: target.label, url: target.url, links }, null, 2));
      } catch (error) {
        console.log(JSON.stringify({ label: target.label, url: target.url, error: error.message }, null, 2));
      }
    }
  } finally {
    await client.close();
  }
})().catch((error) => { console.error("FATAL", error.message); process.exit(1); });
