const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");
const {
  buildReport,
  classifyPage,
  parseArgs,
} = require("./audit_full_crawl_v2");

assert.deepStrictEqual(classifyPage({ status: "error", statusCode: 404 }), {
  status: "terminalError", statusCode: 404, detail: "http404",
});
assert.strictEqual(classifyPage({ status: "error", statusCode: 405 }).status, "terminalError");
assert.strictEqual(classifyPage({ status: "error", statusCode: 410 }).status, "terminalError");
assert.strictEqual(classifyPage({ status: "error", statusCode: 429 }).status, "retryableError");
assert.strictEqual(classifyPage({ status: "error", statusCode: 503 }).status, "retryableError");
assert.strictEqual(classifyPage({ status: "error", error: "SSL certificate failure" }).status, "retryableError");
assert.strictEqual(classifyPage({ status: "error", error: "ERR_TOO_MANY_REDIRECTS" }).status, "redirectError");
assert.strictEqual(classifyPage({ status: "blocked", statusCode: 403 }).status, "blocked");
assert.strictEqual(classifyPage({ status: "captured", statusCode: 200 }).status, "captured");
assert.strictEqual(classifyPage({ status: "loading" }).status, "pending");

const temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), "rankingselect-audit-v2-"));
try {
  const corpus = path.join(temporaryRoot, "raw");
  const targetsFile = path.join(temporaryRoot, "targets.json");
  const outputFile = path.join(temporaryRoot, "reports", "coverage.json");
  const targets = [
    { universityId: "u_closed", name: "Closed University", rankingEntryCount: 2, indexUrl: "https://closed.edu/masters" },
    { universityId: "u_retry", name: "Retry University", indexUrl: "https://retry.edu/masters" },
    { universityId: "u_running", name: "Running University" },
  ];
  fs.writeFileSync(targetsFile, JSON.stringify(targets), "utf8");

  const writeManifest = (id, manifest) => {
    const directory = path.join(corpus, id);
    fs.mkdirSync(directory, { recursive: true });
    fs.writeFileSync(path.join(directory, "manifest.json"), JSON.stringify(manifest), "utf8");
  };
  writeManifest("u_closed", {
    status: "raw-partial",
    discovery: {
      status: "complete",
      queue: [],
      visited: { "https://closed.edu/masters": { status: "captured", statusCode: 200 } },
      programCandidates: { "https://closed.edu/program": { url: "https://closed.edu/program" } },
      evidenceCandidates: {},
    },
    pages: {
      "https://closed.edu/program": { status: "captured", statusCode: 200 },
      "https://closed.edu/gone": { status: "error", statusCode: 404, error: "HTTP Error 404" },
      "https://closed.edu/blocked": { status: "blocked", statusCode: 403 },
      "https://closed.edu/redirect": { status: "error", error: "ERR_TOO_MANY_REDIRECTS" },
    },
  });
  writeManifest("u_retry", {
    status: "raw-complete",
    discovery: {
      status: "partial",
      queue: [{ url: "https://retry.edu/next" }],
      visited: { "https://retry.edu/masters": { status: "captured", statusCode: 200 } },
      programCandidates: {},
      evidenceCandidates: {},
    },
    pages: {
      "https://retry.edu/server-error": { status: "error", statusCode: 503 },
      "https://retry.edu/ssl": { status: "error", error: "SSL CERTIFICATE_VERIFY_FAILED" },
      "https://retry.edu/pending": { status: "pending" },
    },
  });
  writeManifest("u_running", {
    status: "raw-partial",
    discovery: { status: "running", queue: [], visited: {}, programCandidates: {}, evidenceCandidates: {} },
    pages: {},
  });

  const report = buildReport(targets, corpus);
  assert.strictEqual(report.targetCount, 3);
  assert.strictEqual(report.rankingEntryTarget, 4);
  assert.strictEqual(report.strictComplete, 1);
  assert.strictEqual(report.rankingEntriesStrictComplete, 1);
  assert.strictEqual(report.rawDataClosed, 2);
  assert.strictEqual(report.rankingEntriesRawDataClosed, 3);
  assert.strictEqual(report.zeroCandidates.count, 2);
  assert.deepStrictEqual(report.zeroCandidates.universityIds, ["u_retry", "u_running"]);
  assert.strictEqual(report.discovery.running, 1);
  assert.strictEqual(report.discovery.partial, 1);
  assert.strictEqual(report.discovery.queuedDirectories, 1);
  assert.strictEqual(report.pageStatusTotals.terminalError, 1);
  assert.strictEqual(report.pageStatusTotals.retryableError, 2);
  assert.strictEqual(report.pageStatusTotals.redirectError, 1);
  assert.strictEqual(report.pageStatusTotals.blocked, 1);
  assert.strictEqual(report.terminalErrorBreakdown.http404, 1);

  const closed = report.rows.find(row => row.universityId === "u_closed");
  assert.strictEqual(closed.rawDataClosed, true);
  assert.strictEqual(closed.strictComplete, false);
  const retry = report.rows.find(row => row.universityId === "u_retry");
  assert.strictEqual(retry.rawDataClosed, false);
  assert.strictEqual(retry.strictComplete, true);
  assert.ok(retry.pageStatusCounts.pending >= 1, "partial discovery must remain pending");

  const parsed = parseArgs(["--targets", targetsFile, "--corpus", corpus, "--output", outputFile]);
  assert.strictEqual(parsed.output, path.resolve(outputFile));
  const cli = spawnSync(process.execPath, [
    path.join(__dirname, "audit_full_crawl_v2.js"),
    "--targets", targetsFile,
    "--corpus", corpus,
    "--output", outputFile,
  ], { encoding: "utf8" });
  assert.strictEqual(cli.status, 0, cli.stderr);
  const written = JSON.parse(fs.readFileSync(outputFile, "utf8"));
  assert.strictEqual(written.schemaVersion, 2);
  assert.strictEqual(written.rawDataClosed, 2);
  assert.strictEqual(fs.existsSync(path.join(corpus, "u_closed", "manifest.json.tmp")), false);
} finally {
  fs.rmSync(temporaryRoot, { recursive: true, force: true });
}

console.log("[audit-full-crawl-v2-test] passed");
