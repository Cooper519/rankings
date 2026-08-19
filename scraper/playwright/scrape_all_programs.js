const { McpClient } = require("./mcp_client");
const fs = require("fs");
const CAT = process.argv[2] || "program_catalog_all.json";
const LIMIT = parseInt(process.argv[3] || "15", 10);
const K_PROG = 3;            // programs per university
const WAIT = 2.5;
const PROG = "_crawl_progress.json";
const RAW = "_programs_all_raw.json";
const t0 = Date.now();
const log = (...a) => console.log("[" + ((Date.now()-t0)/1000).toFixed(1) + "s]", ...a);
const parse = (txt) => JSON.parse(txt.replace(/^### Result\s*/, "").split(/\n### Ran Playwright/)[0]);

const CATALOG = JSON.parse(fs.readFileSync(__dirname + "/" + CAT, "utf8"));
const SE = fs.readFileSync(__dirname + "/eval_bing.js", "utf8").trim();
const DISCOVER = fs.readFileSync(__dirname + "/eval_discover.js", "utf8").trim();
const EXTRACT = fs.readFileSync(__dirname + "/eval_extract.js", "utf8").trim();

const JUNK = /wikipedia|daad\.de|mygermanuniversity|studyportals|studyq|topuniversities|timeshighereducation|qs\.com|shanghairanking|usnews|masterstudies|onlinestudies|educations\.com|findamasters|mastersportal|phdstudies|bachelorsmasters|study\.eu|youtube|facebook|linkedin|instagram|twitter|reddit|glassdoor|indeed|timeshighered|4icu|webometrics|unirank|collegedunia|shiksha|hotcourses|brighthub|degreequery/i;
const STOP = new Set(["university","of","and","the","for","at","in","de","di","et","universität","universidad","universite","università","universitet","hochschule","school","institute","technology","sciences","science","applied","polytechnic","college","engineering"]);

function nameTokens(name) {
  return (name || "").split(/[\s\-,.()]+/).filter(w => w && w.length > 3 && !STOP.has(w.toLowerCase()));
}

function scoreResult(r, tokens) {
  if (JUNK.test(r.host || "")) return -100;
  let s = 3;
  const tl = (r.title || "").toLowerCase(), hl = (r.href || "").toLowerCase();
  if (/master|programme|program\b|msc|\bstudy\b|admission|education|degree/i.test(tl)) s += 2;
  if (/master|programme|program|study|admission|education|msc|degree/i.test(hl)) s += 2;
  if (tokens.some(t => tl.includes(t.toLowerCase()))) s += 1;
  return s;
}

function pickResult(results, tokens) {
  let best = null, bs = -999;
  for (const r of results) {
    const s = scoreResult(r, tokens);
    if (s > bs) { bs = s; best = r; }
  }
  if (!best || bs < 0) best = results.find(r => !JUNK.test(r.host || "")) || results[0] || null;
  return best;
}

// load state
let progress = {};
try { progress = JSON.parse(fs.readFileSync(PROG, "utf8")); } catch (e) {}
let raw = [];
try { raw = JSON.parse(fs.readFileSync(RAW, "utf8")); } catch (e) {}
function flush() {
  fs.writeFileSync(PROG, JSON.stringify(progress), "utf8");
  fs.writeFileSync(RAW, JSON.stringify(raw), "utf8");
}

const DEPTWO = `() => {
  const re = /master|programme|program\\b|msc|\\bstudy\\b|education|degree/i;
  const here = location.href.split("#")[0];
  const out = [];
  document.querySelectorAll("a[href]").forEach(a => {
    const h = (a.href||"").split("#")[0]; if (!h || h === here) return;
    const t = (a.innerText||a.textContent||"").replace(/\\s+/g," ").trim(); if (t.length<4) return;
    try { const u = new URL(h, location.href); if (u.host !== location.host) return; } catch(e){ return; }
    if (/^(home|back|next|prev|menu|search|login|contact|about|cookie|skip|footer)/i.test(t)) return;
    if (re.test(t) || re.test(h)) out.push({ href: h, text: t.slice(0,120) });
  });
  const seen = new Set(); return out.filter(x=>{ if(seen.has(x.href))return false; seen.add(x.href); return true; }).slice(0,8);
}`;

(async () => {
  const c = new McpClient({ headless: false });
  let done = 0;
  try {
    await c.init();
    for (const uni of CATALOG) {
      if (progress[uni.universityId] && progress[uni.universityId].done) continue;
      if (done >= LIMIT) break;
      log("=== [" + (done+1) + "] " + uni.name + " (" + uni.country + ")");
      let found = 0, listHref = "";
      try {
        const q = encodeURIComponent(uni.name + " master programmes english admission");
        await c.navigate("https://www.bing.com/search?q=" + q);
        await c.waitFor(WAIT);
        const so = parse(await c.eval(SE));
        const results = (so && so.sample) || [];
        const tokens = nameTokens(uni.name);
        let target = pickResult(results, tokens);
        if (!target) { log("  no search results; skip"); progress[uni.universityId] = { done: true, found: 0 }; flush(); done++; continue; }
        listHref = target.href;
        log("  list: " + (target.host || "") + " :: " + (target.title || "").slice(0,60));

        // navigate list page
        let links = [];
        await c.navigate(listHref); await c.waitFor(WAIT);
        links = parse(await c.eval(DISCOVER)) || [];
        log("  discovered: " + links.length);

        // depth-2 hop if nothing found
        if (links.length === 0) {
          try {
            const hop = parse(await c.eval(DEPTWO)) || [];
            if (hop.length) {
              log("  hop -> " + hop[0].text.slice(0,40));
              await c.navigate(hop[0].href); await c.waitFor(WAIT);
              links = parse(await c.eval(DISCOVER)) || [];
              log("  discovered after hop: " + links.length);
            }
          } catch (e) {}
        }

        if (links.length === 0) {
          // try second search result
          const alt = results.find((r, i) => i > 0 && r.href !== listHref && !JUNK.test(r.host || ""));
          if (alt) {
            log("  retry alt: " + (alt.host || ""));
            await c.navigate(alt.href); await c.waitFor(WAIT);
            links = parse(await c.eval(DISCOVER)) || [];
            log("  discovered(alt): " + links.length);
            if (links.length) listHref = alt.href;
          }
        }

        const chosen = links.slice(0, K_PROG);
        for (const lk of chosen) {
          try {
            await c.navigate(lk.href); await c.waitFor(WAIT);
            const o = parse(await c.eval(EXTRACT));
            if (!o || !o.title) continue;
            raw.push({ universityId: uni.universityId, universityName: uni.name,
                       subject: o.subject, program: o.title, sourceUrl: o.url,
                       deadlines: o.deadlines, materials: o.materials,
                       requirements: { gpa: null, ielts: o.ielts, toefl: o.toefl },
                       verified: false, updatedAt: new Date().toISOString().slice(0,10) });
            found++;
            log("    + " + o.subject + " :: " + o.title.slice(0,60));
          } catch (e) { log("    prog err: " + e.message); }
        }
        progress[uni.universityId] = { done: true, found, listHref };
      } catch (e) {
        log("  uni err: " + e.message);
        progress[uni.universityId] = { done: true, found: 0, err: e.message };
      }
      flush();
      done++;
    }
    flush();
    log("chunk done: processed " + done + " this run; raw total " + raw.length);
  } finally { await c.close(); }
})().catch(e => { console.error("FATAL", e.message); process.exit(1); });