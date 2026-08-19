const fs = require("fs");
const path = require("path");
const { safeId, urlKey } = require("./full_crawl_lib");

const ROOT = __dirname;
const DEFAULT_TARGETS = path.join(ROOT, "raw_crawl_targets.json");
const DEFAULT_CORPUS = path.join(ROOT, "_programs_full_raw");
const PAGE_STATUSES = [
  "pending",
  "terminalError",
  "retryableError",
  "redirectError",
  "blocked",
  "captured",
];

function readJson(file, fallback = null) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch (error) {
    return fallback;
  }
}

function targetsFrom(value) {
  if (Array.isArray(value)) return value;
  if (Array.isArray(value?.targets)) return value.targets;
  return [];
}

function statusCodeOf(record) {
  if (!record || typeof record !== "object") return null;
  for (const key of ["statusCode", "httpStatus", "httpStatusCode", "responseStatus"]) {
    const value = Number(record[key]);
    if (Number.isInteger(value) && value >= 100 && value <= 599) return value;
  }
  if (typeof record.status === "number" && Number.isInteger(record.status)) return record.status;
  const match = String(record.error || record.message || "").match(/\bHTTP(?:\s+Error)?[\s:]+([1-5]\d\d)\b/i);
  return match ? Number(match[1]) : null;
}

function terminalDetail(statusCode) {
  if (statusCode === 404) return "http404";
  if (statusCode === 410) return "http410";
  if (statusCode === 405) return "http405";
  return "otherTerminal";
}

function classifyPage(record) {
  const item = record && typeof record === "object" ? record : {};
  const state = String(item.status || "").toLowerCase();
  const error = String(item.error || item.message || "");
  const code = statusCodeOf(item);

  if (["pending", "loading", "queued", "not-started"].includes(state)) {
    return { status: "pending", statusCode: code, detail: state || "pending" };
  }
  if (state === "captured" || state === "complete" || state === "success") {
    return { status: "captured", statusCode: code, detail: null };
  }
  if (
    state.includes("redirect") ||
    (code !== null && code >= 300 && code < 400) ||
    /too many redirects|redirect loop|maximum redirects|err_too_many_redirects/i.test(error)
  ) {
    return { status: "redirectError", statusCode: code, detail: code ? `http${code}` : "redirectFailure" };
  }
  if ([404, 405, 410].includes(code)) {
    return { status: "terminalError", statusCode: code, detail: terminalDetail(code) };
  }
  if (
    state === "blocked" ||
    item.blocked === true ||
    [401, 403, 406, 451].includes(code) ||
    /access denied|captcha|cloudflare|forbidden|robot check|verify you are human/i.test(error)
  ) {
    return { status: "blocked", statusCode: code, detail: code ? `http${code}` : "accessBlocked" };
  }
  if (
    code === null ||
    [408, 425, 429].includes(code) ||
    code >= 500 ||
    /ssl|certificate|econn|connection|socket|network|timed?\s*out|timeout|dns|enotfound|eai_again|closed|browser is already in use/i.test(error)
  ) {
    return { status: "retryableError", statusCode: code, detail: code ? `http${code}` : "noHttpStatus" };
  }

  // Unspecified HTTP failures remain retryable so they cannot silently close raw capture.
  return { status: "retryableError", statusCode: code, detail: `http${code}` };
}

function emptyPageCounts() {
  return Object.fromEntries(PAGE_STATUSES.map(status => [status, 0]));
}

function urlOf(value) {
  if (typeof value === "string") return value;
  return value?.url || value?.href || null;
}

function inventoryFor(target, manifest) {
  const inventory = new Map();
  const put = (url, record, source, overwrite = true) => {
    if (!url) return;
    const key = String(url).startsWith("audit://") ? String(url) : (urlKey(String(url)) || String(url));
    if (!overwrite && inventory.has(key)) return;
    inventory.set(key, { record: record || {}, source });
  };

  const targetSeeds = [
    target.indexUrl,
    ...(target.catalogPages || []),
    ...(target.programUrls || []),
    ...(target.evidenceUrls || []),
    ...(target.apiEndpoints || []),
  ];
  for (const raw of targetSeeds) put(urlOf(raw), { status: "pending" }, "target", false);

  const discovery = manifest?.discovery || {};
  for (const [bucketName, bucket] of [
    ["programCandidates", discovery.programCandidates],
    ["evidenceCandidates", discovery.evidenceCandidates],
  ]) {
    for (const [key, candidate] of Object.entries(bucket || {})) {
      put(urlOf(candidate) || key, { ...candidate, status: "pending" }, `discovery.${bucketName}`, false);
    }
  }
  for (const [url, visit] of Object.entries(discovery.visited || {})) put(url, visit, "discovery.visited");
  for (const [url, page] of Object.entries(manifest?.pages || {})) put(url, page, "pages");

  if (!manifest && inventory.size === 0) {
    put(`audit://target/${target.universityId}`, { status: "pending" }, "missing-manifest");
  }
  return inventory;
}

function auditTarget(target, corpusRoot) {
  const manifestFile = path.join(corpusRoot, safeId(target.universityId), "manifest.json");
  const manifest = readJson(manifestFile, null);
  const pageStatusCounts = emptyPageCounts();
  const terminalErrorBreakdown = { http404: 0, http405: 0, http410: 0, otherTerminal: 0 };
  const pages = [];

  for (const [url, item] of inventoryFor(target, manifest)) {
    const classified = classifyPage(item.record);
    pageStatusCounts[classified.status] += 1;
    if (classified.status === "terminalError") terminalErrorBreakdown[classified.detail] += 1;
    pages.push({
      url,
      status: classified.status,
      statusCode: classified.statusCode,
      detail: classified.detail,
      source: item.source,
      kind: item.record.kind || null,
      error: item.record.error || item.record.message || null,
    });
  }
  pages.sort((left, right) => left.url.localeCompare(right.url));

  const programCandidates = Object.keys(manifest?.discovery?.programCandidates || {}).length;
  const status = manifest?.status || "not-started";
  return {
    universityId: target.universityId,
    name: target.name,
    country: target.country || "",
    status,
    strictComplete: status === "raw-complete",
    discoveryStatus: manifest?.discovery?.status || "not-started",
    discoveryQueue: Array.isArray(manifest?.discovery?.queue) ? manifest.discovery.queue.length : 0,
    rawDataClosed: pageStatusCounts.pending === 0 && pageStatusCounts.retryableError === 0,
    zeroCandidates: programCandidates === 0,
    programCandidates,
    pageStatusCounts,
    terminalErrorBreakdown,
    manifest: manifest ? path.relative(ROOT, manifestFile).replace(/\\/g, "/") : null,
    pages,
  };
}

function increment(result, key, amount = 1) {
  result[key] = (result[key] || 0) + amount;
}

function buildReport(targets, corpusRoot) {
  const rows = targets.map(target => auditTarget(target, corpusRoot));
  const statuses = {};
  const discoveryStatuses = {};
  const pageStatusTotals = emptyPageCounts();
  const terminalErrorBreakdown = { http404: 0, http405: 0, http410: 0, otherTerminal: 0 };
  let rankingEntryTarget = 0;
  let rankingEntriesStrictComplete = 0;
  let rankingEntriesRawDataClosed = 0;

  rows.forEach((row, index) => {
    const weight = Number(targets[index].rankingEntryCount ?? 1);
    rankingEntryTarget += weight;
    if (row.strictComplete) rankingEntriesStrictComplete += weight;
    if (row.rawDataClosed) rankingEntriesRawDataClosed += weight;
    increment(statuses, row.status);
    increment(discoveryStatuses, row.discoveryStatus);
    for (const status of PAGE_STATUSES) pageStatusTotals[status] += row.pageStatusCounts[status];
    for (const key of Object.keys(terminalErrorBreakdown)) terminalErrorBreakdown[key] += row.terminalErrorBreakdown[key];
  });

  return {
    schemaVersion: 2,
    generatedAt: new Date().toISOString(),
    targetCount: rows.length,
    rankingEntryTarget,
    rankingEntriesStrictComplete,
    rankingEntriesRawDataClosed,
    strictComplete: rows.filter(row => row.strictComplete).length,
    rawDataClosed: rows.filter(row => row.rawDataClosed).length,
    zeroCandidates: {
      count: rows.filter(row => row.zeroCandidates).length,
      universityIds: rows.filter(row => row.zeroCandidates).map(row => row.universityId),
    },
    discovery: {
      running: discoveryStatuses.running || 0,
      partial: discoveryStatuses.partial || 0,
      queuedDirectories: rows.reduce((sum, row) => sum + row.discoveryQueue, 0),
      statuses: discoveryStatuses,
    },
    statuses,
    pageStatusTotals,
    terminalErrorBreakdown,
    rows,
  };
}

function parseArgs(argv) {
  const options = { targets: null, corpus: null, output: null, help: false };
  const positional = [];
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--help" || arg === "-h") options.help = true;
    else if (["--targets", "--corpus", "--output"].includes(arg)) {
      const key = arg.slice(2);
      if (!argv[index + 1]) throw new Error(`${arg} requires a path`);
      options[key] = argv[index += 1];
    } else if (arg.startsWith("--")) throw new Error(`unknown option: ${arg}`);
    else positional.push(arg);
  }
  options.targets ||= positional[0] || DEFAULT_TARGETS;
  options.corpus ||= positional[1] || DEFAULT_CORPUS;
  options.output ||= positional[2] || path.join(options.corpus, "_coverage_report_v2.json");
  for (const key of ["targets", "corpus", "output"]) options[key] = path.resolve(options[key]);
  return options;
}

function writeReport(report, outputFile) {
  fs.mkdirSync(path.dirname(outputFile), { recursive: true });
  const temporary = `${outputFile}.tmp-${process.pid}`;
  fs.writeFileSync(temporary, JSON.stringify(report, null, 2), "utf8");
  fs.renameSync(temporary, outputFile);
}

function run(options) {
  const targets = targetsFrom(readJson(options.targets, []));
  if (!targets.length) throw new Error(`no targets found in ${options.targets}`);
  const report = buildReport(targets, options.corpus);
  writeReport(report, options.output);
  return report;
}

function usage() {
  console.log("Usage: node audit_full_crawl_v2.js [targets.json] [corpus-dir] [output.json]");
  console.log("   or: node audit_full_crawl_v2.js --targets FILE --corpus DIR --output FILE");
}

if (require.main === module) {
  try {
    const options = parseArgs(process.argv.slice(2));
    if (options.help) usage();
    else {
      const report = run(options);
      console.log(JSON.stringify({
        targetCount: report.targetCount,
        strictComplete: report.strictComplete,
        rawDataClosed: report.rawDataClosed,
        zeroCandidates: report.zeroCandidates.count,
        discovery: report.discovery,
        pageStatusTotals: report.pageStatusTotals,
        outputFile: options.output,
      }, null, 2));
    }
  } catch (error) {
    console.error(`[audit-full-crawl-v2] ${error.stack || error.message}`);
    process.exitCode = 1;
  }
}

module.exports = {
  PAGE_STATUSES,
  auditTarget,
  buildReport,
  classifyPage,
  inventoryFor,
  parseArgs,
  run,
  statusCodeOf,
  targetsFrom,
  writeReport,
};
