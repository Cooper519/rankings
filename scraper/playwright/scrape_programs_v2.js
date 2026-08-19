const { McpClient } = require("./mcp_client");
const fs = require("fs");

const QUEUE_FILE = process.argv[2] || "program_crawl_queue.json";
const LIMIT = parseInt(process.argv[3] || "12", 10);
const MAX_PER_UNI = parseInt(process.argv[4] || "24", 10);
const MAX_RETRIES = 3;
const WAIT = 2.5;
const STATE_FILE = "_crawl_progress_v2.json";
const RAW_FILE = "_programs_v2_raw.json";
const t0 = Date.now();
const log = (...args) => console.log("[" + ((Date.now() - t0) / 1000).toFixed(1) + "s]", ...args);
const parse = (text) => JSON.parse(text.replace(/^### Result\s*/, "").split(/\n### Ran Playwright/)[0]);

const queue = JSON.parse(fs.readFileSync(__dirname + "/" + QUEUE_FILE, "utf8"));
const searchEval = fs.readFileSync(__dirname + "/eval_bing.js", "utf8").trim();
const discoverEval = fs.readFileSync(__dirname + "/eval_discover.js", "utf8").trim();
const extractEval = fs.readFileSync(__dirname + "/eval_extract.js", "utf8").trim();
const relatedEval = fs.readFileSync(__dirname + "/eval_related.js", "utf8").trim();
const FORCE_RETRY = process.argv.includes("--retry");

const DENY = /wikipedia|daad\.de|mygermanuniversity|studyportals|mastersportal|findamasters|masterstudies|mastermania|globalstudyprep|standyou|goaustria|educations\.com|university-directory|globaladmissions|collegelearners|topuniversities|timeshighereducation|shanghairanking|usnews|reddit|linkedin|facebook|instagram|youtube/i;
const TRUSTED_CENTRAL = new Set(["studyinfo.fi", "universityadmissions.se"]);
const JUNK_TITLE = /cookie|privacy|accessibility|homepage|navigation|search|404|not found|403|forbidden|access denied|just a moment|cloudflare|this website uses|^programmes?$|^programs?$|^master.?s programmes?$|^all programmes?$|^masters?$|^bachelors?$|^study programmes?$|^degree programmes?$|^graduate programmes?$|open day|prepare for your studies|admission requirements?|application procedure|how (?:and when )?to apply|tuition fees?|entry requirements?|\bwebinars?\b|graduation ceremony|\banniversary\b|^idex programs?$|^les programmes europ(?:e|é)ens de recherche$|^chef d[ '’]?equipe$|^polydaire$|^eco marathon shell$|^stages?$/i;
const NON_CATALOG_URL = /admission-and-application|\/admission\/?$|\/apply\/?$|how-to-apply|application-procedure|requirements?\/??$/i;
const NON_PROGRAM_PATH = /\/(?:research|recherche|innovation|news|actualites?|articles?|events?|webinars?|admissions?|application|application-registration|exchange|scholarships?|information-activities|how-to-register|master-theses|mobility-programmes|incoming-students|tuition-fees?|fees-and-funding|moving-to-france|current-students(?:-\d+)?|administrative-procedures|health-insurance(?:-\d+)?|banks-insurances|accommodation|sponsorship)(?:\/|$)|\/(?:[^/]*webinar[^/]*|[^/]*graduation-ceremony[^/]*|[^/]*-anniversary(?:-|\/|$))/i;
const GENERIC_SECTION = /^(in the same section|dans la m.me rubrique)(?:\s+\1)*$/i;
const NON_MASTER_TITLE = /\b(?:bachelor|undergraduate|doctoral|doctorate|ph\.?d\.?)\b/i;
const STOP = new Set(["university", "universite", "universitat", "universidad", "institute", "technology", "technical", "school", "college", "science", "sciences", "royal", "the", "and", "for", "of"]);

function load(path, fallback) {
  try { return JSON.parse(fs.readFileSync(__dirname + "/" + path, "utf8")); }
  catch (e) { return fallback; }
}

let state = load(STATE_FILE, {});
let raw = load(RAW_FILE, []);

function flush() {
  fs.writeFileSync(__dirname + "/" + STATE_FILE, JSON.stringify(state, null, 2), "utf8");
  fs.writeFileSync(__dirname + "/" + RAW_FILE, JSON.stringify(raw, null, 2), "utf8");
}

function host(url) {
  try { return new URL(url).hostname.toLowerCase().replace(/^www\./, ""); }
  catch (e) { return ""; }
}

function nameTokens(name) {
  return (name || "").toLowerCase().split(/[^a-z0-9]+/).filter(w => w.length > 3 && !STOP.has(w));
}

function sameDomain(candidate, officialDomains) {
  const h = host(candidate);
  return officialDomains.some(d => h === d || h.endsWith("." + d) || d.endsWith("." + h));
}

function isNonProgramUrl(url) {
  try { return NON_PROGRAM_PATH.test(decodeURIComponent(new URL(url).pathname) + "/"); }
  catch (e) { return true; }
}

function searchScore(result, uni) {
  const h = host(result.href || "");
  if (!h || DENY.test(h)) return -100;
  const text = ((result.title || "") + " " + (result.href || "")).toLowerCase();
  const tokens = nameTokens(uni.name);
  let score = 0;
  if (sameDomain(result.href, uni.officialDomains || [])) score += 10;
  if (TRUSTED_CENTRAL.has(h)) score += 3;
  score += Math.min(4, tokens.filter(t => text.includes(t)).length * 2);
  if (/master|msc|graduate|degree.program|study.program/.test(text)) score += 4;
  if (/admission|apply|application/.test(text)) score += 1;
  if (/programmes?|degree-programs?|study-programmes?|\/masters?\//.test((result.href || "").toLowerCase())) score += 5;
  if (NON_CATALOG_URL.test(result.href || "")) score -= 10;
  return score;
}

function chooseSearchResult(results, uni) {
  return results
    .map(result => ({ result, score: searchScore(result, uni) }))
    .filter(x => x.score >= 4)
    .sort((a, b) => b.score - a.score)[0]?.result || null;
}

function mergeArray(left, right, key) {
  const result = [...(left || [])];
  const seen = new Set(result.map(key));
  for (const item of right || []) {
    const id = key(item);
    if (!seen.has(id)) { seen.add(id); result.push(item); }
  }
  return result;
}

function titleFromUrl(url) {
  try {
    const path = decodeURIComponent(new URL(url).pathname).replace(/\/$/, "");
    if (isNonProgramUrl(url)) return "";
    const slug = path.split("/").filter(Boolean).pop() || "";
    if (!slug || /^(master|masters|program|programs|programme|programmes|all-programmes|international-study-programmes|specialized-master-degree)$/i.test(slug) || /20\d{2}/.test(slug)) return "";
    const words = slug.split(/[-_]+/).filter(Boolean);
    if (!words.length || words.length > 12) return "";
    return words.map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(" ");
  } catch (e) { return ""; }
}

function mergeExtract(base, extra, sourceUrl, fieldSources) {
  if (!extra) return base;
  if ((extra.deadlines || []).length) {
    base.deadlines = mergeArray(base.deadlines, extra.deadlines, x => (x.round || "") + "|" + (x.date || ""));
    fieldSources.deadlines.push(sourceUrl);
  }
  if ((extra.materials || []).length) {
    base.materials = mergeArray(base.materials, extra.materials, x => x.toLowerCase());
    fieldSources.materials.push(sourceUrl);
  }
  if (!base.ielts && extra.ielts) { base.ielts = extra.ielts; fieldSources.requirements.push(sourceUrl); }
  if (!base.toefl && extra.toefl) { base.toefl = extra.toefl; fieldSources.requirements.push(sourceUrl); }
  if (!base.gpa && extra.gpa) { base.gpa = extra.gpa; fieldSources.requirements.push(sourceUrl); }
  if (!base.language && extra.language) { base.language = extra.language; fieldSources.requirements.push(sourceUrl); }
  if (!base.academic && extra.academic) { base.academic = extra.academic; fieldSources.requirements.push(sourceUrl); }
  return base;
}

function queueLinks(uni) {
  if (!Array.isArray(uni.programUrls)) return [];
  return uni.programUrls.map(item => {
    if (typeof item === "string") return { href: item, text: titleFromUrl(item) };
    return { href: item.url || item.href || "", text: item.title || item.text || "" };
  }).filter(item => item.href);
}

async function discoverCatalog(client, url) {
  await client.navigate(url);
  await client.waitFor(WAIT);
  // Trigger lazy-loaded lists before extracting anchors.
  try { await client.eval("async () => { for (let i=0;i<5;i++){ window.scrollTo(0, document.body.scrollHeight); await new Promise(r=>setTimeout(r,450)); } window.scrollTo(0,0); return document.links.length; }"); } catch (e) {}
  return parse(await client.eval(discoverEval)) || [];
}

async function findCatalog(client, uni) {
  if (uni.indexUrl && !DENY.test(host(uni.indexUrl)) && !NON_CATALOG_URL.test(uni.indexUrl)) {
    return { url: uni.indexUrl, method: "known-index" };
  }
  const queries = [
    uni.name + " official master programmes",
    uni.name + " official graduate degree programmes admission",
  ];
  for (const query of queries) {
    await client.navigate("https://www.bing.com/search?q=" + encodeURIComponent(query));
    await client.waitFor(WAIT);
    const result = parse(await client.eval(searchEval));
    const chosen = chooseSearchResult((result && result.sample) || [], uni);
    if (chosen) return { url: chosen.href, method: "search" };
  }
  return null;
}

(async () => {
  const client = new McpClient({ headless: true });
  let processed = 0;
  try {
    await client.init();
    for (const uni of queue) {
      const previous = state[uni.universityId] || {};
      if (!FORCE_RETRY && (previous.status === "complete" || (previous.status === "partial" && (previous.found || 0) > 0))) continue;
      if ((previous.attempts || 0) >= MAX_RETRIES && previous.status === "failed") continue;
      if (processed >= LIMIT) break;
      processed++;
      const startedAt = new Date().toISOString();
      state[uni.universityId] = { ...previous, status: "discovering", attempts: (previous.attempts || 0) + 1, startedAt };
      flush();
      log("===", uni.name, "attempt", state[uni.universityId].attempts);
      let found = 0;
      let blockedPages = 0;
      try {
        const catalog = await findCatalog(client, uni);
        if (!catalog) throw new Error("official catalog not found");
        const catalogHost = host(catalog.url);
        if (!catalogHost || DENY.test(catalogHost)) throw new Error("catalog is not an allowed official source");
        log("catalog", catalogHost, catalog.method);
        let links = queueLinks(uni);
        if (!links.length) {
          const pages = Array.isArray(uni.catalogPages) && uni.catalogPages.length ? uni.catalogPages : [catalog.url];
          for (const pageUrl of pages) links.push(...await discoverCatalog(client, pageUrl));
        }
        const officialDomains = [...new Set([...(uni.officialDomains || []), catalogHost])];
        links = links.filter(link => !DENY.test(host(link.href)) && sameDomain(link.href, officialDomains));
        let unique = [];
        const seen = new Set();
        for (const link of links) {
          const clean = (link.href || "").split("#")[0];
          if (!clean || seen.has(clean)) continue;
          seen.add(clean); unique.push({ ...link, href: clean });
        }
        unique = unique.filter(link => !JUNK_TITLE.test((link.text || "").trim()) && !NON_CATALOG_URL.test(link.href) && !isNonProgramUrl(link.href));
        if (!unique.length) throw new Error("catalog rendered but no program detail links were discovered");
        const chosen = unique.slice(0, MAX_PER_UNI);
        log("program candidates", chosen.length, "of", unique.length);
        const commonEvidence = [];
        for (const evidenceUrl of (uni.evidenceUrls || []).slice(0, 4)) {
          if (!sameDomain(evidenceUrl, officialDomains) || DENY.test(host(evidenceUrl))) continue;
          try {
            await client.navigate(evidenceUrl);
            await client.waitFor(1.5);
            commonEvidence.push({ url: evidenceUrl, data: parse(await client.eval(extractEval)) });
          } catch (e) {
            log(" evidence error", e.message);
          }
        }
        for (const link of chosen) {
          const cleanLink = (link.href || "").split("#")[0].replace(/\/$/, "").toLowerCase();
          if (raw.some(record => record.universityId === uni.universityId && (record.sourceUrl || "").split("#")[0].replace(/\/$/, "").toLowerCase() === cleanLink)) {
            found++;
            continue;
          }
          try {
            await client.navigate(link.href);
            await client.waitFor(WAIT);
            const detail = parse(await client.eval(extractEval));
            if (detail && detail.blocked) { blockedPages++; continue; }
            if (!detail || !detail.title || detail.title.length < 4) continue;
            if (GENERIC_SECTION.test(detail.title)) detail.title = (link.text && !GENERIC_SECTION.test(link.text) ? link.text : "") || titleFromUrl(detail.url || link.href);
            if (!detail.title || JUNK_TITLE.test(detail.title)) continue;
            if (NON_MASTER_TITLE.test(detail.title)) continue;
            if (!/^https?:\/\//i.test(detail.url || link.href)) continue;
            if (isNonProgramUrl(detail.url || link.href)) continue;
            const detailHost = host(detail.url || link.href);
            if (!detailHost || !sameDomain(detail.url || link.href, officialDomains)) continue;
            const evidenceUrls = [detail.url || link.href];
            const fieldSources = { deadlines: [], materials: [], requirements: [] };
            const merged = {
              ...detail,
              deadlines: detail.deadlines || [], materials: detail.materials || [],
              ielts: detail.ielts || null, toefl: detail.toefl || null, gpa: detail.gpa || null,
              language: detail.language || null, academic: detail.academic || null,
            };
            mergeExtract({ deadlines: [], materials: [], ielts: null, toefl: null, gpa: null }, detail, evidenceUrls[0], fieldSources);
            for (const evidence of commonEvidence) {
              evidenceUrls.push(evidence.url);
              mergeExtract(merged, evidence.data, evidence.url, fieldSources);
            }
            const related = parse(await client.eval(relatedEval)) || [];
            for (const rel of related.slice(0, 3)) {
              try {
                await client.navigate(rel.href);
                await client.waitFor(1.5);
                const extra = parse(await client.eval(extractEval));
                evidenceUrls.push(rel.href);
                mergeExtract(merged, extra, rel.href, fieldSources);
              } catch (e) {}
            }
            raw.push({
              universityId: uni.universityId,
              universityName: uni.name,
              subject: merged.subject || "General",
              program: detail.title,
              sourceUrl: detail.url || link.href,
              deadlines: merged.deadlines || [],
              materials: merged.materials || [],
              requirements: {
                gpa: merged.gpa || null,
                ielts: merged.ielts || null,
                toefl: merged.toefl || null,
                language: merged.language || null,
                academic: merged.academic || null,
              },
              evidenceUrls: [...new Set(evidenceUrls)],
              fieldSources: {
                deadlines: [...new Set(fieldSources.deadlines)],
                materials: [...new Set(fieldSources.materials)],
                requirements: [...new Set(fieldSources.requirements)],
              },
              catalogUrl: catalog.url,
              officialDomains,
              verified: false,
              updatedAt: new Date().toISOString().slice(0, 10),
            });
            found++;
            log(" +", detail.title.slice(0, 65), "dl=" + (merged.deadlines || []).length, "req=" + !!(merged.ielts || merged.toefl || merged.gpa));
            flush();
          } catch (error) {
            log(" program error", error.message);
          }
        }
        if (!found) throw new Error(blockedPages ? "blocked_waf" : "program pages were found but extraction returned zero valid records");
        state[uni.universityId] = {
          ...state[uni.universityId], status: found >= Math.min(MAX_PER_UNI, unique.length) ? "complete" : "partial",
          found, catalogUrl: catalog.url, candidateCount: unique.length, completedAt: new Date().toISOString(), failureReason: null, qualityRejected: 0,
        };
      } catch (error) {
        state[uni.universityId] = {
          ...state[uni.universityId], status: "failed", found, failureReason: error.message,
          completedAt: new Date().toISOString(),
        };
        log(" failed", error.message);
      }
      flush();
    }
    log("batch done", processed, "raw total", raw.length);
  } finally {
    await client.close();
  }
})().catch(error => { console.error("FATAL", error.message); process.exit(1); });
