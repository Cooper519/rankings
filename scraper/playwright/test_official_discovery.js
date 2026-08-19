const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const vm = require("vm");
const {
  appendJsonl,
  buildQueries,
  completedIdsFromJsonl,
  deniedHost,
  normalizeSearchResult,
  isQualifiedCandidate,
  parseArgs,
  queueItems,
  scoreCandidate,
  sameSearchQuery,
  selectShard,
} = require("./discover_top500_official");

assert.deepStrictEqual(queueItems({ items: [{ canonicalId: "u_b" }] }), [{ canonicalId: "u_b" }]);
assert.deepStrictEqual(queueItems({ queue: [{ canonicalId: "u_a" }] }), [{ canonicalId: "u_a" }]);

const target = {
  universityId: "u_test",
  name: "Technical University of Example",
  country: "Germany",
  rankingSources: ["qs", "the"],
};

assert.deepStrictEqual(
  buildQueries({ ...target, registryDomainHints: ["example.edu"] }),
  [
    'site:example.edu "Example University" graduate programs',
    'site:example.edu (master OR postgraduate) (program OR degree OR course)',
  ],
);

const strong = scoreCandidate({
  title: "Master's degree programmes - Technical University of Example",
  snippet: "Graduate study catalog at the university in Germany.",
  href: "https://study.example.edu/degree-programmes/masters",
}, target);
assert.strictEqual(strong.denied, false);
assert(strong.rawScore >= 20, `expected strong score, got ${strong.rawScore}`);
assert.deepStrictEqual(strong.scoreSignals, {
  nameTokenHits: 1,
  nameTokenTotal: 1,
  countryHint: true,
  graduateSemantics: true,
  catalogSemantics: true,
});

const weak = scoreCandidate({
  title: "Unrelated undergraduate admissions",
  snippet: "Another country",
  href: "https://example.org/bachelor",
}, target);
assert(weak.rawScore < strong.rawScore);

const denied = scoreCandidate({
  title: "Technical University of Example masters",
  snippet: "Germany programmes",
  href: "https://www.mastersportal.com/studies/123",
}, target);
assert.strictEqual(denied.denied, true);
assert.strictEqual(denied.rawScore, -1000);
assert.strictEqual(deniedHost("sub.mastersportal.com"), "mastersportal.com");

const normalized = normalizeSearchResult({
  title: "  Result   title ",
  href: "https://www.mastersportal.com/studies/123",
  snippet: " summary ",
  rawRank: 2,
}, target, "query");
assert.strictEqual(normalized.verificationStatus, "candidate");
assert.strictEqual(normalized.query, "query");
assert.strictEqual(normalized.host, "mastersportal.com");
assert.strictEqual(normalized.denied, true);
assert(!Object.prototype.hasOwnProperty.call(normalized, "official"));
assert.strictEqual(isQualifiedCandidate(normalized), false);
assert.strictEqual(isQualifiedCandidate({ denied: false, scoreSignals: {
  nameTokenHits: 1, graduateSemantics: true, catalogSemantics: true,
} }), true);
assert.strictEqual(isQualifiedCandidate({ denied: false, scoreSignals: {
  nameTokenHits: 0, graduateSemantics: true, catalogSemantics: true,
} }), false);
assert.strictEqual(sameSearchQuery("A  B", "a b"), true);
assert.strictEqual(sameSearchQuery("wrong query", "a b"), false);

const targets = Array.from({ length: 9 }, (_, index) => ({ universityId: String(index) }));
const shards = [0, 1, 2].map(workerIndex => selectShard(targets, workerIndex, 3));
assert.deepStrictEqual(shards.map(shard => shard.map(item => item.universityId)), [
  ["0", "3", "6"],
  ["1", "4", "7"],
  ["2", "5", "8"],
]);
assert.strictEqual(new Set(shards.flat().map(item => item.universityId)).size, 9);
assert.deepStrictEqual(selectShard(targets, 1, 3, 2).map(item => item.universityId), ["1", "4"]);
assert.deepStrictEqual(selectShard(targets, 1, 3).map(item => item.universityId), ["1", "4", "7"]);

const options = parseArgs(["--worker-index", "2", "--worker-count", "4", "--limit", "5", "--resume"]);
assert.strictEqual(options.workerIndex, 2);
assert.strictEqual(options.workerCount, 4);
assert.strictEqual(options.limit, 5);
assert.strictEqual(options.resume, true);
assert.throws(() => parseArgs(["--worker-index", "2", "--worker-count", "2"]), /worker-index/);

assert.strictEqual(buildQueries(target).length, 2);
assert(buildQueries(target).every(query => query.includes(target.name)));

const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "rankingselect-discovery-"));
try {
  const jsonl = path.join(temporary, "0.jsonl");
  appendJsonl(jsonl, { universityId: "done", status: "completed" });
  appendJsonl(jsonl, { universityId: "retry", status: "partial" });
  fs.appendFileSync(jsonl, '{"universityId":"interrupted"', "utf8");
  const completed = completedIdsFromJsonl(jsonl);
  assert.deepStrictEqual([...completed], ["done"]);
} finally {
  fs.rmSync(temporary, { recursive: true, force: true });
}

const evaluator = fs.readFileSync(path.join(__dirname, "eval_official_search.js"), "utf8").trim();
assert.doesNotThrow(() => new vm.Script(`(${evaluator})`));
for (const field of ["title", "href", "snippet", "host", "rawRank"]) {
  assert(evaluator.includes(field), `browser evaluator must preserve ${field}`);
}

console.log("[official-discovery-test] passed");
