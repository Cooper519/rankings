const fs = require("fs");
const path = require("path");
const zlib = require("zlib");
const { McpClient } = require("./mcp_client");
const {
  allowedUrl,
  hashUrl,
  hostOf,
  mergeTargets,
  normalizeLink,
  parseArgs,
  readJson,
  safeId,
  selectTargets,
  urlKey,
  writeJsonAtomic,
} = require("./full_crawl_lib");

const ROOT = __dirname;
const t0 = Date.now();
const log = (...args) => console.log("[" + ((Date.now() - t0) / 1000).toFixed(1) + "s]", ...args);
const parseResult = text => JSON.parse(String(text || "").replace(/^### Result\s*/, "").split(/\n### Ran Playwright/)[0]);
const SEARCH_DENY = /wikipedia|daad\.de|mygermanuniversity|studyportals|mastersportal|findamasters|masterstudies|educations\.com|topuniversities|timeshighereducation|shanghairanking|usnews|reddit|linkedin|facebook|instagram|youtube/i;
const SEARCH_STOP = new Set(["university", "universite", "universitat", "universidad", "institute", "technology", "technical", "school", "college", "science", "sciences", "royal", "the", "and", "for", "of"]);

function usage() {
  console.log(`Usage: node scraper/playwright/scrape_programs_full.js [options]

  --targets FILE             Target list (default raw_crawl_targets.json)
  --university ID            Crawl one university; repeatable
  --limit N                  Maximum universities for this run
  --worker-index N           Zero-based deterministic shard index
  --worker-count N           Number of deterministic shards
  --max-detail-pages-per-run N  Bound one resumable detail-page pass (default 40)
  --max-catalog-pages-per-run N Bound one catalogue pass (default 80)
  --discovery-only           Build manifests without capturing detail pages
  --retry-errors             Retry failed/blocked detail pages
  --force-discovery          Re-run completed catalogue discovery
  --headed                   Show Chromium

Raw output is written per university below scraper/playwright/_programs_full_raw.
No deadline, requirement, title, or quality cleaning occurs in this command.`);
}

function loadEvaluator(primary, fallback) {
  const primaryPath = path.join(ROOT, primary);
  return fs.readFileSync(fs.existsSync(primaryPath) ? primaryPath : path.join(ROOT, fallback), "utf8").trim();
}

function loadTargets(options) {
  const targetFile = path.resolve(ROOT, options.targets);
  const base = readJson(targetFile, []);
  if (!Array.isArray(base) || !base.length) throw new Error("target file is empty or missing: " + targetFile);
  const overrides = options.overrides
    .map(file => readJson(path.resolve(ROOT, file), []))
    .filter(Array.isArray);
  return mergeTargets(base, overrides);
}

function initialManifest(target) {
  const now = new Date().toISOString();
  return {
    schemaVersion: 1,
    universityId: target.universityId,
    universityName: target.name,
    country: target.country || "",
    region: target.region || "",
    officialDomains: target.officialDomains || [],
    indexUrl: target.indexUrl || "",
    discoveryStrategy: target.discoveryStrategy || "recursive-catalog",
    status: "pending",
    discovery: {
      status: "pending",
      queue: [],
      visited: {},
      programCandidates: {},
      categoryCandidates: {},
      paginationCandidates: {},
      evidenceCandidates: {},
      apiEndpoints: target.apiEndpoints || [],
      searchAttempted: false,
      searchCandidates: [],
      selectedSearchResult: null,
      startedAt: null,
      completedAt: null,
      stoppedReason: null,
    },
    pages: {},
    counts: { catalogsVisited: 0, programCandidates: 0, captured: 0, blocked: 0, errors: 0, pending: 0 },
    createdAt: now,
    updatedAt: now,
  };
}

function updateCounts(manifest) {
  for (const page of Object.values(manifest.pages || {})) {
    if (page.status === "loading") page.status = "pending";
  }
  const pages = Object.values(manifest.pages || {});
  manifest.counts = {
    catalogsVisited: Object.keys(manifest.discovery.visited || {}).length,
    programCandidates: Object.keys(manifest.discovery.programCandidates || {}).length,
    captured: pages.filter(page => page.status === "captured").length,
    blocked: pages.filter(page => page.status === "blocked").length,
    errors: pages.filter(page => page.status === "error").length,
    pending: pages.filter(page => page.status === "pending").length,
  };
  manifest.updatedAt = new Date().toISOString();
}

function seedDiscovery(manifest, target) {
  const seeds = [];
  if (target.indexUrl) seeds.push({ url: target.indexUrl, kind: "catalog", depth: 0, sourceUrl: null });
  for (const url of target.catalogPages || []) seeds.push({ url, kind: "catalog", depth: 0, sourceUrl: target.indexUrl || null });
  const queued = new Set((manifest.discovery.queue || []).map(item => urlKey(item.url)));
  const visited = new Set(Object.keys(manifest.discovery.visited || {}));
  for (const seed of seeds) {
    seed.url = urlKey(seed.url);
    if (seed.url && !queued.has(seed.url) && !visited.has(seed.url)) {
      manifest.discovery.queue.push(seed);
      queued.add(seed.url);
    }
  }
  for (const item of target.programUrls || []) {
    const link = normalizeLink(item, "program");
    if (link.url) manifest.discovery.programCandidates[link.url] = { ...link, kind: "program", sourceUrl: target.indexUrl || null };
  }
  // API endpoints are raw evidence sources. They are captured losslessly as
  // pages even when a site-specific parser has not been implemented yet.
  for (const rawUrl of target.apiEndpoints || []) {
    const url = urlKey(rawUrl);
    if (!url || !allowedUrl(url, manifest.officialDomains)) continue;
    if (!manifest.discovery.apiEndpoints.includes(url)) manifest.discovery.apiEndpoints.push(url);
    manifest.pages[url] ||= {
      status: "pending",
      kind: "api",
      text: "official catalogue API",
      sourceUrl: target.indexUrl || null,
      attempts: 0,
    };
  }
}

function nameTokens(name) {
  return String(name || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter(token => token.length > 3 && !SEARCH_STOP.has(token));
}

function searchScore(result, target) {
  const href = result.href || "";
  const host = hostOf(href);
  if (!host || SEARCH_DENY.test(host)) return -100;
  const text = (String(result.title || "") + " " + href)
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
  const tokens = nameTokens(target.name);
  const tokenHits = tokens.filter(token => text.includes(token)).length;
  if (tokens.length && tokenHits === 0) return -50;
  let score = Math.min(tokenHits * 3, 9);
  if (/(?:master|msc|graduate|second.?cycle|postgraduate)/.test(text)) score += 5;
  if (/(?:program|programme|degree|curricul|course|study)/.test(text)) score += 4;
  if (/(?:all|list|catalog|find|search)/.test(text)) score += 2;
  if (/(?:professional.?master|executive|continuing.?education|phd|doctoral|bachelor|undergraduate)/.test(text)) score -= 8;
  if (/(?:admission|application|how.?to.?apply|requirements?)(?:\/|$)/.test(href.toLowerCase())) score -= 5;
  return score;
}

async function searchOfficialCatalog(client, target, manifest, searchEvaluator, options) {
  if (manifest.discovery.searchAttempted) return null;
  manifest.discovery.searchAttempted = true;
  const candidates = [];
  const seen = new Set();
  for (const query of [
    `\"${target.name}\" official master degree programmes`,
    `\"${target.name}\" master programmes catalog`,
  ]) {
    try {
      await client.navigate("https://www.bing.com/search?q=" + encodeURIComponent(query));
      await client.waitFor(options.wait);
      const result = parseResult(await client.eval(searchEvaluator)) || {};
      for (const item of result.sample || []) {
        const url = urlKey(item.href);
        if (!url || seen.has(url)) continue;
        seen.add(url);
        candidates.push({ ...item, href: url, score: searchScore(item, target), query });
      }
    } catch (error) {
      manifest.discovery.searchError = error.message;
    }
  }
  candidates.sort((left, right) => right.score - left.score);
  manifest.discovery.searchCandidates = candidates;
  const selected = candidates.find(candidate => candidate.score >= 7) || null;
  if (!selected) return null;
  manifest.discovery.selectedSearchResult = selected;
  manifest.indexUrl ||= selected.href;
  const selectedHost = hostOf(selected.href);
  if (selectedHost && !manifest.officialDomains.includes(selectedHost)) manifest.officialDomains.push(selectedHost);
  target.indexUrl ||= selected.href;
  target.officialDomains = [...new Set([...(target.officialDomains || []), selectedHost])].filter(Boolean);
  return { url: selected.href, kind: "catalog", depth: 0, sourceUrl: null };
}

function addDiscoveryLinks(manifest, target, sourceUrl, sourceDepth, discovered, options) {
  const domains = manifest.officialDomains;
  const queued = new Set(manifest.discovery.queue.map(item => urlKey(item.url)));
  const visited = new Set(Object.keys(manifest.discovery.visited));
  const groups = [
    ["program", discovered.programs || discovered.programLinks || []],
    ["category", discovered.categories || discovered.categoryLinks || []],
    ["pagination", discovered.pagination || discovered.paginationLinks || discovered.nextPages || []],
  ];
  for (const [kind, links] of groups) {
    for (const rawLink of links) {
      const link = normalizeLink(rawLink, kind);
      if (!link.url || !allowedUrl(link.url, domains)) continue;
      const value = { ...link, kind, sourceUrl };
      if (kind === "program") {
        if (Object.keys(manifest.discovery.programCandidates).length < options.maxCandidates) {
          manifest.discovery.programCandidates[link.url] = value;
        }
        continue;
      }
      const depth = kind === "pagination" ? sourceDepth : sourceDepth + 1;
      const bucket = kind === "pagination" ? manifest.discovery.paginationCandidates : manifest.discovery.categoryCandidates;
      bucket[link.url] = value;
      if (depth <= options.maxDepth && !queued.has(link.url) && !visited.has(link.url)) {
        manifest.discovery.queue.push({ url: link.url, kind, depth, sourceUrl });
        queued.add(link.url);
      }
    }
  }
}

async function preparePage(client, wait) {
  await client.waitFor(wait);
  try {
    await client.eval(`async () => {
      const clickMore = () => [...document.querySelectorAll('button,a')].filter(node => /^(?:load|show|view) more|more results|see more$/i.test((node.innerText || '').trim())).slice(0, 5);
      for (let round = 0; round < 8; round++) {
        for (const node of clickMore()) { try { node.click(); } catch (error) {} }
        window.scrollTo(0, document.body.scrollHeight);
        await new Promise(resolve => setTimeout(resolve, 450));
      }
      window.scrollTo(0, 0);
      return { links: document.links.length, height: document.body.scrollHeight };
    }`);
  } catch (error) {}
}

async function discoverUniversity(client, target, manifest, manifestFile, evaluator, options) {
  if (manifest.discovery.status === "complete" && !options.forceDiscovery) return;
  if (options.forceDiscovery) {
    manifest.discovery.queue = [];
    manifest.discovery.visited = {};
    manifest.discovery.categoryCandidates = {};
    manifest.discovery.paginationCandidates = {};
    manifest.discovery.status = "pending";
  }
  seedDiscovery(manifest, target);
  for (const [url, visit] of Object.entries(manifest.discovery.visited || {})) {
    if (visit.captureMethod === "static-http" && (visit.dynamicShell || visit.status === "blocked" || visit.status === "error")) {
      delete manifest.discovery.visited[url];
      if (!manifest.discovery.queue.some(item => urlKey(item.url) === urlKey(url))) {
        manifest.discovery.queue.unshift({ url, kind: visit.kind || "catalog", depth: visit.depth || 0, sourceUrl: visit.sourceUrl || null });
      }
    }
  }
  const searchEvaluator = fs.readFileSync(path.join(ROOT, "eval_bing.js"), "utf8").trim();
  if (!manifest.discovery.queue.length && !Object.keys(manifest.discovery.programCandidates).length) {
    const searched = await searchOfficialCatalog(client, target, manifest, searchEvaluator, options);
    if (searched) manifest.discovery.queue.push(searched);
  }
  manifest.discovery.status = "running";
  manifest.discovery.startedAt ||= new Date().toISOString();
  writeJsonAtomic(manifestFile, manifest);
  let visitedThisRun = 0;
  while (manifest.discovery.queue.length && Object.keys(manifest.discovery.visited).length < options.maxCatalogPages && visitedThisRun < options.maxCatalogPagesPerRun) {
    const item = manifest.discovery.queue.shift();
    const pageUrl = urlKey(item.url);
    if (!pageUrl || manifest.discovery.visited[pageUrl]) continue;
    log(" catalog", target.name, item.kind, "d=" + item.depth, pageUrl);
    const visit = { status: "loading", kind: item.kind, depth: item.depth, sourceUrl: item.sourceUrl || null, startedAt: new Date().toISOString() };
    manifest.discovery.visited[pageUrl] = visit;
    visitedThisRun++;
    try {
      await client.navigate(pageUrl);
      await preparePage(client, options.wait);
      let result = parseResult(await client.eval(evaluator)) || {};
      if (Array.isArray(result)) result = { programs: result, categories: [], pagination: [] };
      visit.status = result.blocked ? "blocked" : "captured";
      visit.finalUrl = result.url || pageUrl;
      visit.title = result.title || "";
      visit.programLinks = (result.programs || result.programLinks || []).length;
      visit.categoryLinks = (result.categories || result.categoryLinks || []).length;
      visit.paginationLinks = (result.pagination || result.paginationLinks || result.nextPages || []).length;
      visit.completedAt = new Date().toISOString();
      addDiscoveryLinks(manifest, target, pageUrl, item.depth, result, options);
    } catch (error) {
      visit.status = "error";
      visit.error = error.message;
      visit.completedAt = new Date().toISOString();
    }
    updateCounts(manifest);
    writeJsonAtomic(manifestFile, manifest);
  }
  if (!manifest.discovery.queue.length && !Object.keys(manifest.discovery.programCandidates).length && !manifest.discovery.searchAttempted) {
    const searched = await searchOfficialCatalog(client, target, manifest, searchEvaluator, options);
    if (searched) {
      manifest.discovery.queue.push(searched);
      return discoverUniversity(client, target, manifest, manifestFile, evaluator, options);
    }
  }
  const exhausted = manifest.discovery.queue.length === 0;
  const candidateCount = Object.keys(manifest.discovery.programCandidates).length;
  manifest.discovery.status = exhausted && candidateCount > 0 ? "complete" : "partial";
  manifest.discovery.stoppedReason = !exhausted ? (visitedThisRun >= options.maxCatalogPagesPerRun ? "catalog-run-budget" : "max-catalog-pages") : candidateCount ? null : "no-program-candidates";
  manifest.discovery.completedAt = new Date().toISOString();
  for (const candidate of Object.values(manifest.discovery.programCandidates)) {
    const key = urlKey(candidate.url);
    if (!key || manifest.pages[key]) continue;
    manifest.pages[key] = { status: "pending", kind: "program", text: candidate.text || "", sourceUrl: candidate.sourceUrl || null, attempts: 0 };
  }
  updateCounts(manifest);
  writeJsonAtomic(manifestFile, manifest);
}

function writeSnapshot(outputDir, pageUrl, record) {
  const pagesDir = path.join(outputDir, "pages");
  fs.mkdirSync(pagesDir, { recursive: true });
  const filename = hashUrl(pageUrl) + ".json.gz";
  const finalPath = path.join(pagesDir, filename);
  const temporary = finalPath + ".tmp-" + process.pid;
  fs.writeFileSync(temporary, zlib.gzipSync(Buffer.from(JSON.stringify(record), "utf8"), { level: 9 }));
  fs.renameSync(temporary, finalPath);
  return "pages/" + filename;
}

async function captureUniversity(client, target, manifest, manifestFile, outputDir, evaluator, options) {
  if (options.discoveryOnly) return;
  let processedThisRun = 0;
  for (const [pageUrl, page] of Object.entries(manifest.pages)) {
    if (processedThisRun >= options.maxDetailPagesPerRun) break;
    if (page.status === "captured" && !page.dynamicShell) continue;
    if (!options.retryErrors && (page.status === "error" || page.status === "blocked")) continue;
    page.attempts = Number(page.attempts || 0) + 1;
    processedThisRun++;
    page.status = "loading";
    page.startedAt = new Date().toISOString();
    updateCounts(manifest);
    writeJsonAtomic(manifestFile, manifest);
    log("  page", target.name, pageUrl);
    try {
      await client.navigate(pageUrl);
      await preparePage(client, options.wait);
      const raw = parseResult(await client.eval(evaluator));
      const snapshot = {
        schemaVersion: 1,
        universityId: target.universityId,
        universityName: target.name,
        sourceUrl: pageUrl,
        discoveredFrom: page.sourceUrl || target.indexUrl || null,
        capturedAt: new Date().toISOString(),
        raw,
      };
      page.file = writeSnapshot(outputDir, pageUrl, snapshot);
      page.finalUrl = raw.requestedUrl || pageUrl;
      page.documentTitle = raw.documentTitle || "";
      page.textLength = Number(raw.textLength || 0);
      page.status = raw.blocked ? "blocked" : "captured";
      page.error = null;
      if ((page.kind || "program") === "program") {
        for (const related of raw.relatedLinks || []) {
          const relatedUrl = urlKey(related.url);
          if (!relatedUrl || !allowedUrl(relatedUrl, manifest.officialDomains)) continue;
          manifest.discovery.evidenceCandidates[relatedUrl] ||= { ...related, sourceUrl: pageUrl };
          manifest.pages[relatedUrl] ||= { status: "pending", kind: "evidence", text: related.text || "", sourceUrl: pageUrl, attempts: 0 };
        }
      }
    } catch (error) {
      page.status = "error";
      page.error = error.message;
    }
    page.completedAt = new Date().toISOString();
    updateCounts(manifest);
    writeJsonAtomic(manifestFile, manifest);
  }
}

function finalizeManifest(manifest) {
  updateCounts(manifest);
  const discoveryDone = manifest.discovery.status === "complete";
  if (!discoveryDone || !manifest.counts.programCandidates || manifest.counts.errors || manifest.counts.blocked || manifest.counts.pending) manifest.status = "raw-partial";
  else manifest.status = "raw-complete";
  manifest.completedAt = new Date().toISOString();
}

(async () => {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) return usage();
  const targets = selectTargets(loadTargets(options), options);
  if (!targets.length) throw new Error("no targets selected");
  const discoverEvaluator = loadEvaluator("eval_catalog_discover.js", "eval_discover.js");
  const rawEvaluator = fs.readFileSync(path.join(ROOT, "eval_raw_capture.js"), "utf8").trim();
  const corpusRoot = path.resolve(ROOT, options.output);
  fs.mkdirSync(corpusRoot, { recursive: true });
  log("selected", targets.length, "universities; worker", options.workerIndex + "/" + options.workerCount);
  const client = new McpClient({ headless: !options.headed });
  try {
    await client.init();
    for (let index = 0; index < targets.length; index++) {
      const target = targets[index];
      const outputDir = path.join(corpusRoot, safeId(target.universityId));
      const manifestFile = path.join(outputDir, "manifest.json");
      let manifest = readJson(manifestFile, null) || initialManifest(target);
      manifest.discovery.evidenceCandidates ||= {};
      manifest.discovery.searchCandidates ||= [];
      manifest.discovery.programCandidates ||= {};
      manifest.discovery.categoryCandidates ||= {};
      manifest.discovery.paginationCandidates ||= {};
      manifest.discovery.queue ||= [];
      manifest.discovery.visited ||= {};
      manifest.pages ||= {};
      manifest.officialDomains = [...new Set([...(manifest.officialDomains || []), ...(target.officialDomains || []), hostOf(target.indexUrl)])].filter(Boolean);
      if (manifest.status === "raw-complete" && !options.forceDiscovery && !options.retryErrors) {
        log("skip complete", target.name);
        continue;
      }
      log("===", index + 1 + "/" + targets.length, target.name);
      try {
        await discoverUniversity(client, target, manifest, manifestFile, discoverEvaluator, options);
        await captureUniversity(client, target, manifest, manifestFile, outputDir, rawEvaluator, options);
      } catch (error) {
        manifest.lastError = error.message;
        log(" university error", error.message);
      }
      finalizeManifest(manifest);
      writeJsonAtomic(manifestFile, manifest);
      log(" result", manifest.status, JSON.stringify(manifest.counts));
    }
  } finally {
    await client.close();
  }
})().catch(error => {
  console.error("FATAL", error.stack || error.message);
  process.exit(1);
});
