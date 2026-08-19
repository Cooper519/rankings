const { McpClient } = require("./mcp_client");
const fs = require("fs");
const CATALOG = JSON.parse(fs.readFileSync(__dirname + "/" + (process.argv[2] || "program_catalog.json"), "utf8"));
const DISCOVER = fs.readFileSync(__dirname + "/eval_discover.js", "utf8").trim();
const EXTRACT = fs.readFileSync(__dirname + "/eval_extract.js", "utf8").trim();
const OUT = "_programs_raw.json";
const MAX_PER_UNI = 6;
const WAIT = 2.0;
const t0 = Date.now();
const log = (...a) => console.log("[" + ((Date.now()-t0)/1000).toFixed(1) + "s]", ...a);
const parse = (txt) => JSON.parse(txt.replace(/^### Result\s*/, "").split(/\n### Ran Playwright/)[0]);

(async () => {
  const all = [];
  const c = new McpClient({ headless: false });
  try {
    await c.init();
    for (const uni of CATALOG) {
      log("=== " + uni.name + " :: " + uni.indexUrl);
      let links = [];
      try {
        await c.navigate(uni.indexUrl);
        await c.waitFor(uni.wait || 3);
        const t = await c.eval(DISCOVER);
        links = parse(t) || [];
        log("  discovered " + links.length + " candidate links");
        if (links.length === 0) { log("  (no links; skip)"); continue; }
      } catch (e) { log("  index err: " + e.message); continue; }
      const chosen = links.slice(0, MAX_PER_UNI);
      for (const lk of chosen) {
        try {
          await c.navigate(lk.href);
          await c.waitFor(uni.wait || 3);
          const t = await c.eval(EXTRACT);
          const o = parse(t);
          if (!o || !o.title) { log("    skip (no title): " + lk.href); continue; }
          all.push({ universityId: uni.universityId, universityName: uni.name,
                     subject: o.subject, program: o.title, sourceUrl: o.url,
                     deadlines: o.deadlines, materials: o.materials,
                     requirements: { gpa: null, ielts: o.ielts, toefl: o.toefl },
                     verified: false, updatedAt: new Date().toISOString().slice(0,10) });
          log("    + " + o.subject + " :: " + o.title.slice(0,70) + " (dl=" + o.deadlines.length + " mat=" + o.materials.length + " ielts=" + o.ielts + ")");
        } catch (e) { log("    prog err: " + e.message); }
        fs.writeFileSync(OUT, JSON.stringify(all), "utf8");
      }
      log("  -> " + uni.name + " running total: " + all.length);
    }
    fs.writeFileSync(OUT, JSON.stringify(all), "utf8");
    log("DONE: " + all.length + " programs -> " + OUT);
  } finally { await c.close(); }
})().catch(e => { console.error("FATAL", e.message); process.exit(1); });