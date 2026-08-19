const fs = require("fs");
const path = require("path");
const { readJson, safeId } = require("./full_crawl_lib");

const ROOT = __dirname;
const targetFile = path.resolve(ROOT, process.argv[2] || "raw_crawl_targets.json");
const corpusRoot = path.resolve(ROOT, process.argv[3] || "_programs_full_raw");
const outputFile = path.join(corpusRoot, "_coverage_report.json");
const targets = readJson(targetFile, []);
const rankingEntryTarget = targets.reduce((sum, target) => sum + Number(target.rankingEntryCount ?? 1), 0);
const rows = targets.map(target => {
  const manifestFile = path.join(corpusRoot, safeId(target.universityId), "manifest.json");
  const manifest = readJson(manifestFile, null);
  return {
    universityId: target.universityId,
    name: target.name,
    country: target.country || "",
    status: manifest?.status || "not-started",
    discoveryStatus: manifest?.discovery?.status || "not-started",
    ...(manifest?.counts || { catalogsVisited: 0, programCandidates: 0, captured: 0, blocked: 0, errors: 0, pending: 0 }),
    manifest: manifest ? path.relative(ROOT, manifestFile).replace(/\\/g, "/") : null,
  };
});
const statuses = rows.reduce((result, row) => {
  result[row.status] = (result[row.status] || 0) + 1;
  return result;
}, {});
const totals = rows.reduce((result, row) => {
  for (const field of ["catalogsVisited", "programCandidates", "captured", "blocked", "errors", "pending"]) result[field] += row[field] || 0;
  return result;
}, { catalogsVisited: 0, programCandidates: 0, captured: 0, blocked: 0, errors: 0, pending: 0 });
const report = { generatedAt: new Date().toISOString(), targetCount: rows.length, statuses, totals, rows };
report.rankingEntryTarget = rankingEntryTarget;
report.rankingEntriesCovered = targets.reduce((sum, target, index) => {
  return sum + (rows[index].status === "raw-complete" ? Number(target.rankingEntryCount ?? 1) : 0);
}, 0);
fs.mkdirSync(corpusRoot, { recursive: true });
fs.writeFileSync(outputFile, JSON.stringify(report, null, 2), "utf8");
console.log(JSON.stringify({ targetCount: rows.length, rankingEntryTarget, rankingEntriesCovered: report.rankingEntriesCovered, statuses, totals, outputFile }, null, 2));
