const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const DENIED_HOSTS = /(?:^|\.)(?:wikipedia\.org|daad\.de|mygermanuniversity\.com|studyportals\.com|mastersportal\.com|findamasters\.com|masterstudies\.com|educations\.com|study\.eu|topuniversities\.com|timeshighereducation\.com|shanghairanking\.com|usnews\.com|reddit\.com|linkedin\.com|facebook\.com|instagram\.com|youtube\.com|globalstudyprep\.com|globaladmissions\.com|university-directory\.eu|collegelearners\.org|studyindenmark\.dk)$/i;

function readJson(file, fallback) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8").replace(/^\uFEFF/, ""));
  } catch (error) {
    if (error.code === "ENOENT") return fallback;
    throw error;
  }
}

function writeJsonAtomic(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const temporary = file + ".tmp-" + process.pid;
  fs.writeFileSync(temporary, JSON.stringify(value, null, 2), "utf8");
  fs.renameSync(temporary, file);
}

function safeId(value) {
  return String(value || "unknown")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-zA-Z0-9._-]+/g, "_")
    .replace(/^_+|_+$/g, "") || "unknown";
}

function urlKey(value) {
  try {
    const url = new URL(value);
    url.hash = "";
    for (const key of [...url.searchParams.keys()]) {
      if (/^(?:utm_.+|fbclid|gclid|mc_cid|mc_eid|ref|source)$/i.test(key)) {
        url.searchParams.delete(key);
      }
    }
    if (url.pathname !== "/") url.pathname = url.pathname.replace(/\/+$/, "");
    return url.toString();
  } catch (error) {
    return "";
  }
}

function hostOf(value) {
  try {
    return new URL(value).hostname.toLowerCase().replace(/^www\./, "");
  } catch (error) {
    return "";
  }
}

function allowedUrl(value, officialDomains) {
  const host = hostOf(value);
  if (!host || DENIED_HOSTS.test(host)) return false;
  return (officialDomains || []).some(domain => {
    const clean = String(domain || "").toLowerCase().replace(/^www\./, "");
    return clean && (host === clean || host.endsWith("." + clean) || clean.endsWith("." + host));
  });
}

function hashUrl(value) {
  return crypto.createHash("sha256").update(urlKey(value)).digest("hex").slice(0, 24);
}

function normalizeLink(link, fallbackKind = "category") {
  if (typeof link === "string") return { url: urlKey(link), text: "", kind: fallbackKind, score: 0 };
  return {
    url: urlKey(link.url || link.href || ""),
    text: String(link.text || link.title || "").replace(/\s+/g, " ").trim().slice(0, 500),
    kind: link.kind || fallbackKind,
    score: Number(link.score || 0),
    source: link.source || "anchor",
  };
}

function mergeTargets(baseTargets, overrideGroups) {
  const byId = new Map();
  for (const target of baseTargets || []) {
    if (!target || !target.universityId) continue;
    byId.set(target.universityId, { ...target });
  }
  for (const overrides of overrideGroups || []) {
    for (const override of overrides || []) {
      if (!override || !override.universityId) continue;
      const current = byId.get(override.universityId) || {};
      const merged = { ...current, ...override };
      for (const field of ["officialDomains", "catalogPages", "programUrls", "evidenceUrls", "apiEndpoints"]) {
        merged[field] = [...new Set([...(current[field] || []), ...(override[field] || [])])];
      }
      byId.set(override.universityId, merged);
    }
  }
  return [...byId.values()];
}

function selectTargets(targets, options) {
  let selected = [...targets];
  if (options.universityIds.size) selected = selected.filter(item => options.universityIds.has(item.universityId));
  selected = selected.filter((_, index) => index % options.workerCount === options.workerIndex);
  if (options.offset) selected = selected.slice(options.offset);
  if (Number.isFinite(options.limit)) selected = selected.slice(0, options.limit);
  return selected;
}

function parseArgs(argv) {
  const options = {
    targets: "raw_crawl_targets.json",
    overrides: ["catalog_overrides_priority_a.json", "catalog_overrides_priority_b.json", "catalog_overrides_priority_c.json"],
    output: "_programs_full_raw",
    limit: Infinity,
    offset: 0,
    workerIndex: 0,
    workerCount: 1,
    universityIds: new Set(),
    wait: 2.5,
    maxCatalogPages: 350,
    maxCatalogPagesPerRun: 80,
    maxDepth: 4,
    maxCandidates: 2000,
    maxDetailPagesPerRun: 40,
    retryErrors: false,
    forceDiscovery: false,
    headed: false,
    discoveryOnly: false,
  };
  for (let index = 0; index < argv.length; index++) {
    const arg = argv[index];
    const next = () => argv[++index];
    if (arg === "--targets") options.targets = next();
    else if (arg === "--override") options.overrides.push(next());
    else if (arg === "--no-default-overrides") options.overrides = [];
    else if (arg === "--output") options.output = next();
    else if (arg === "--limit") options.limit = Number(next());
    else if (arg === "--offset") options.offset = Number(next());
    else if (arg === "--worker-index") options.workerIndex = Number(next());
    else if (arg === "--worker-count") options.workerCount = Number(next());
    else if (arg === "--university") options.universityIds.add(next());
    else if (arg === "--wait") options.wait = Number(next());
    else if (arg === "--max-catalog-pages") options.maxCatalogPages = Number(next());
    else if (arg === "--max-catalog-pages-per-run") options.maxCatalogPagesPerRun = Number(next());
    else if (arg === "--max-depth") options.maxDepth = Number(next());
    else if (arg === "--max-candidates") options.maxCandidates = Number(next());
    else if (arg === "--max-detail-pages-per-run") options.maxDetailPagesPerRun = Number(next());
    else if (arg === "--retry-errors") options.retryErrors = true;
    else if (arg === "--force-discovery") options.forceDiscovery = true;
    else if (arg === "--headed") options.headed = true;
    else if (arg === "--discovery-only") options.discoveryOnly = true;
    else if (arg === "--help") options.help = true;
    else throw new Error("unknown argument: " + arg);
  }
  if (!Number.isInteger(options.workerIndex) || !Number.isInteger(options.workerCount) || options.workerCount < 1 || options.workerIndex < 0 || options.workerIndex >= options.workerCount) {
    throw new Error("worker index must be in [0, worker-count)");
  }
  return options;
}

module.exports = {
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
};
