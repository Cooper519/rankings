const fs = require("fs");
const path = require("path");
const { McpClient } = require("./mcp_client");

const ROOT = __dirname;
const DEFAULT_INPUT = "top500_official_discovery_queue.json";
const DEFAULT_OUTPUT = "_top500_official_discovery";
const DENIED_HOSTS = [
  "wikipedia.org",
  "daad.de",
  "mygermanuniversity.com",
  "studyportals.com",
  "mastersportal.com",
  "findamasters.com",
  "masterstudies.com",
  "educations.com",
  "study.eu",
  "topuniversities.com",
  "timeshighereducation.com",
  "shanghairanking.com",
  "usnews.com",
  "reddit.com",
  "linkedin.com",
  "facebook.com",
  "instagram.com",
  "youtube.com",
  "globalstudyprep.com",
  "globaladmissions.com",
  "university-directory.eu",
  "collegelearners.org",
];
const NAME_STOP_WORDS = new Set([
  "and", "college", "for", "institute", "national", "of", "royal", "school",
  "science", "sciences", "the", "technical", "technology", "universidad",
  "universita", "universitat", "universite", "university",
]);

function usage() {
  console.log(`Usage: node scraper/playwright/discover_top500_official.js [options]

  --input FILE       Queue JSON (default ${DEFAULT_INPUT})
  --output DIR       Isolated output directory (default ${DEFAULT_OUTPUT})
  --worker-index N   Zero-based deterministic shard index
  --worker-count N   Number of deterministic shards
  --limit N          Maximum universities in this shard run
  --resume           Skip universities with a completed JSONL record
  --wait SECONDS     Search-result render wait (default 2.5)
  --headed           Show Chromium

Each university is queried exactly twice. Output is <worker-index>.jsonl plus
<worker-index>.summary.json. This command never writes crawl targets or raw manifests.`);
}

function parseArgs(argv) {
  const options = {
    input: DEFAULT_INPUT,
    output: DEFAULT_OUTPUT,
    workerIndex: 0,
    workerCount: 1,
    limit: Infinity,
    resume: false,
    wait: 2.5,
    headed: false,
  };
  for (let index = 0; index < argv.length; index++) {
    const argument = argv[index];
    const next = () => {
      if (index + 1 >= argv.length) throw new Error(`missing value for ${argument}`);
      return argv[++index];
    };
    if (argument === "--input") options.input = next();
    else if (argument === "--output") options.output = next();
    else if (argument === "--worker-index") options.workerIndex = Number(next());
    else if (argument === "--worker-count") options.workerCount = Number(next());
    else if (argument === "--limit") options.limit = Number(next());
    else if (argument === "--wait") options.wait = Number(next());
    else if (argument === "--resume") options.resume = true;
    else if (argument === "--headed") options.headed = true;
    else if (argument === "--help") options.help = true;
    else throw new Error(`unknown argument: ${argument}`);
  }
  if (!Number.isInteger(options.workerCount) || options.workerCount < 1) {
    throw new Error("worker-count must be a positive integer");
  }
  if (!Number.isInteger(options.workerIndex) || options.workerIndex < 0 || options.workerIndex >= options.workerCount) {
    throw new Error("worker-index must be in [0, worker-count)");
  }
  if (!(options.limit >= 0) || (!Number.isFinite(options.limit) && options.limit !== Infinity)) {
    throw new Error("limit must be a non-negative number");
  }
  if (!(options.wait >= 0) || !Number.isFinite(options.wait)) {
    throw new Error("wait must be a non-negative number");
  }
  return options;
}

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, "utf8").replace(/^\uFEFF/, ""));
}

function queueItems(payload) {
  if (Array.isArray(payload)) return payload;
  for (const key of ["items", "queue", "targets", "gaps", "crawlTargetDraft", "entities"]) {
    if (Array.isArray(payload && payload[key])) return payload[key];
  }
  throw new Error("discovery queue must be an array or contain items/queue/targets/gaps/crawlTargetDraft/entities");
}

function normalizeTarget(item, index) {
  const universityId = String(item.universityId || item.canonicalId || item.id || "").trim();
  const name = String(item.name || item.universityName || "").trim();
  if (!universityId || !name) throw new Error(`queue item ${index} is missing universityId/canonicalId or name`);
  return {
    universityId,
    name,
    country: String(item.country || "").trim(),
    rankingSources: Array.isArray(item.rankingSources) ? item.rankingSources : [],
    registryDomainHints: [...new Set((item.registryDomainHints || []).map(value => String(value).toLowerCase().replace(/^www\./, "")).filter(Boolean))],
  };
}

function selectShard(targets, workerIndex, workerCount, limit = Infinity) {
  const selected = targets.filter((target, index) => index % workerCount === workerIndex);
  return Number.isFinite(limit) ? selected.slice(0, Math.floor(limit)) : selected;
}

function normalizeText(value) {
  return String(value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function hostOf(value) {
  try {
    return new URL(value).hostname.toLowerCase().replace(/^www\./, "");
  } catch (error) {
    return "";
  }
}

function deniedHost(host) {
  const clean = String(host || "").toLowerCase().replace(/^www\./, "");
  return DENIED_HOSTS.find(domain => clean === domain || clean.endsWith(`.${domain}`)) || null;
}

function nameTokens(name) {
  return normalizeText(name)
    .split(/[^a-z0-9]+/)
    .filter(token => token.length > 2 && !NAME_STOP_WORDS.has(token));
}

function countryHints(country) {
  const normalized = normalizeText(country).trim();
  const aliases = {
    "czechia": ["czech republic"],
    "hong kong": ["hong kong sar"],
    "south korea": ["korea", "republic of korea"],
    "taiwan": ["chinese taipei"],
    "turkey": ["turkiye"],
    "united kingdom": ["uk", "great britain"],
    "united states": ["usa", "u.s.", "united states of america"],
  };
  return [...new Set([normalized, ...(aliases[normalized] || [])])].filter(Boolean);
}

function scoreCandidate(result, target) {
  const host = hostOf(result.href) || String(result.host || "").toLowerCase().replace(/^www\./, "");
  const deniedDomain = deniedHost(host);
  if (deniedDomain) {
    return {
      rawScore: -1000,
      denied: true,
      denyReason: `third-party-domain:${deniedDomain}`,
      scoreSignals: { nameTokenHits: 0, nameTokenTotal: nameTokens(target.name).length, countryHint: false, graduateSemantics: false, catalogSemantics: false },
    };
  }

  const searchable = normalizeText(`${result.title || ""} ${result.snippet || ""} ${result.href || ""}`);
  const tokens = nameTokens(target.name);
  const hits = tokens.filter(token => searchable.includes(token));
  const hasCountry = countryHints(target.country).some(hint => searchable.includes(hint));
  const graduateSemantics = /\b(master(?:'s|s)?|msc|m\.?sc\.?|graduate|postgraduate|second[ -]?cycle)\b/.test(searchable);
  const catalogSemantics = /\b(programmes?|programs?|degrees?|courses?|study|studies|catalog(?:ue)?|academics?)\b/.test(searchable);
  const admissionOnly = /\b(admissions?|application|apply|requirements?|deadlines?)\b/.test(searchable) && !catalogSemantics;
  let rawScore = Math.min(hits.length * 4, 12);
  if (tokens.length && hits.length === tokens.length) rawScore += 4;
  if (!hits.length && tokens.length) rawScore -= 12;
  if (hasCountry) rawScore += 3;
  if (graduateSemantics) rawScore += 7;
  if (catalogSemantics) rawScore += 5;
  if (admissionOnly) rawScore -= 4;
  if (/\b(bachelor|undergraduate|doctoral|phd|executive education)\b/.test(searchable)) rawScore -= 5;
  return {
    rawScore,
    denied: false,
    denyReason: null,
    scoreSignals: {
      nameTokenHits: hits.length,
      nameTokenTotal: tokens.length,
      countryHint: hasCountry,
      graduateSemantics,
      catalogSemantics,
    },
  };
}

function buildQueries(target) {
  const location = target.country ? ` ${target.country}` : "";
  if (target.registryDomainHints?.length) {
    const domain = target.registryDomainHints[0];
    return [
      `site:${domain} "${target.name}" graduate programs`,
      `site:${domain} (master OR postgraduate) (program OR degree OR course)`,
    ];
  }
  return [
    `"${target.name}"${location} official master programmes`,
    `"${target.name}"${location} graduate degree catalog`,
  ];
}

function parseMcpResult(text) {
  const payload = String(text || "").replace(/^### Result\s*/, "").split(/\n### Ran Playwright/)[0];
  return JSON.parse(payload);
}

function completedIdsFromJsonl(file) {
  const completed = new Set();
  if (!fs.existsSync(file)) return completed;
  for (const line of fs.readFileSync(file, "utf8").split(/\r?\n/)) {
    if (!line.trim()) continue;
    try {
      const row = JSON.parse(line);
      if (row.status === "completed" && row.universityId) completed.add(row.universityId);
    } catch (error) {
      // An interrupted final append is ignored; prior complete lines remain resumable.
    }
  }
  return completed;
}

function appendJsonl(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.appendFileSync(file, JSON.stringify(value) + "\n", "utf8");
}

function writeJsonAtomic(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const temporary = `${file}.tmp-${process.pid}`;
  fs.writeFileSync(temporary, JSON.stringify(value, null, 2), "utf8");
  fs.renameSync(temporary, file);
}

async function createClient(options) {
  const client = new McpClient({ headless: !options.headed, timeoutMs: 90000 });
  await client.init();
  return client;
}

async function runSearch(state, query, evaluator, options) {
  let finalError;
  for (let attempt = 1; attempt <= 2; attempt++) {
    try {
      if (!state.client) state.client = await createClient(options);
      await state.client.navigate(`https://www.bing.com/search?q=${encodeURIComponent(query)}`);
      if (options.wait) await state.client.waitFor(options.wait);
      return parseMcpResult(await state.client.eval(evaluator));
    } catch (error) {
      finalError = error;
      if (state.client) await state.client.close().catch(() => {});
      state.client = null;
    }
  }
  throw finalError;
}

function normalizeSearchResult(result, target, query) {
  const href = String(result.href || "").trim();
  const host = hostOf(href) || String(result.host || "").toLowerCase().replace(/^www\./, "");
  const scored = scoreCandidate({ ...result, href, host }, target);
  return {
    title: String(result.title || "").replace(/\s+/g, " ").trim().slice(0, 500),
    href,
    snippet: String(result.snippet || "").replace(/\s+/g, " ").trim().slice(0, 1500),
    query,
    host,
    rawScore: scored.rawScore,
    rawRank: Number(result.rawRank || 0) || null,
    denied: scored.denied,
    denyReason: scored.denyReason,
    scoreSignals: scored.scoreSignals,
    verificationStatus: "candidate",
  };
}

function sameSearchQuery(actual, expected) {
  const normalize = value => String(value || "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
  return normalize(actual) === normalize(expected);
}

function isQualifiedCandidate(candidate) {
  const signals = candidate && candidate.scoreSignals || {};
  return Boolean(
    candidate && !candidate.denied &&
    signals.nameTokenHits > 0 &&
    signals.graduateSemantics &&
    signals.catalogSemantics
  );
}

async function discoverTarget(state, target, evaluator, options) {
  const queryRuns = [];
  const candidates = [];
  for (const query of buildQueries(target)) {
    try {
      const payload = await runSearch(state, query, evaluator, options);
      const results = Array.isArray(payload.results) ? payload.results : [];
      const queryMatches = sameSearchQuery(payload.urlQuery, query) && sameSearchQuery(payload.inputValue, query);
      queryRuns.push({
        query,
        status: queryMatches ? "completed" : "invalid-search",
        engine: payload.engine || "bing",
        resultCount: results.length,
        locationHref: payload.locationHref || null,
        urlQuery: payload.urlQuery || "",
        inputValue: payload.inputValue || "",
      });
      if (queryMatches) candidates.push(...results.map(result => normalizeSearchResult(result, target, query)));
    } catch (error) {
      queryRuns.push({ query, status: "error", error: error.message });
    }
  }
  candidates.sort((left, right) => right.rawScore - left.rawScore || (left.rawRank || 999) - (right.rawRank || 999));
  const qualifiedCandidates = candidates.filter(isQualifiedCandidate);
  const queriesCompleted = queryRuns.every(run => run.status === "completed");
  const invalidSearch = queryRuns.some(run => run.status === "invalid-search");
  return {
    schemaVersion: 1,
    universityId: target.universityId,
    universityName: target.name,
    country: target.country,
    rankingSources: target.rankingSources,
    registryDomainHints: target.registryDomainHints,
    verificationStatus: "candidate",
    status: !queriesCompleted ? (invalidSearch ? "invalid-search" : "partial") : qualifiedCandidates.length ? "completed" : "no-qualified-candidate",
    queries: queryRuns,
    candidates,
    qualifiedCandidates,
    capturedAt: new Date().toISOString(),
  };
}

async function main(argv = process.argv.slice(2)) {
  const options = parseArgs(argv);
  if (options.help) return usage();
  const inputFile = path.resolve(ROOT, options.input);
  const outputDirectory = path.resolve(ROOT, options.output);
  const shardFile = path.join(outputDirectory, `${options.workerIndex}.jsonl`);
  const summaryFile = path.join(outputDirectory, `${options.workerIndex}.summary.json`);
  const targets = queueItems(readJson(inputFile)).map(normalizeTarget);
  const selected = selectShard(targets, options.workerIndex, options.workerCount, options.limit);
  fs.mkdirSync(outputDirectory, { recursive: true });
  if (!options.resume) fs.writeFileSync(shardFile, "", "utf8");
  const completed = options.resume ? completedIdsFromJsonl(shardFile) : new Set();
  const pending = selected.filter(target => !completed.has(target.universityId));
  const evaluator = fs.readFileSync(path.join(ROOT, "eval_official_search.js"), "utf8").trim();
  const state = { client: null };
  const runStartedAt = new Date().toISOString();
  let processed = 0;
  let completedNow = 0;
  let partialNow = 0;
  let candidateCount = 0;
  let deniedCount = 0;
  try {
    for (const target of pending) {
      const row = await discoverTarget(state, target, evaluator, options);
      appendJsonl(shardFile, row);
      processed++;
      if (row.status === "completed") completedNow++;
      else partialNow++;
      candidateCount += row.candidates.length;
      deniedCount += row.candidates.filter(candidate => candidate.denied).length;
      console.log(`[official-discovery] ${processed}/${pending.length} ${target.universityId} ${row.status} candidates=${row.candidates.length}`);
    }
  } finally {
    if (state.client) await state.client.close().catch(() => {});
    writeJsonAtomic(summaryFile, {
      schemaVersion: 1,
      generatedAt: new Date().toISOString(),
      runStartedAt,
      inputFile,
      shard: { workerIndex: options.workerIndex, workerCount: options.workerCount },
      selectedCount: selected.length,
      resumedCompletedCount: selected.length - pending.length,
      processedCount: processed,
      completedCount: completedNow,
      partialCount: partialNow,
      candidateCount,
      deniedThirdPartyCount: deniedCount,
      outputFile: shardFile,
    });
  }
}

module.exports = {
  DENIED_HOSTS,
  appendJsonl,
  buildQueries,
  completedIdsFromJsonl,
  deniedHost,
  nameTokens,
  normalizeSearchResult,
  sameSearchQuery,
  isQualifiedCandidate,
  normalizeTarget,
  parseArgs,
  queueItems,
  scoreCandidate,
  selectShard,
};

if (require.main === module) {
  main().catch(error => {
    console.error("FATAL", error.message);
    process.exitCode = 1;
  });
}
