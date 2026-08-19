const assert = require("assert");
const {
  allowedUrl,
  hashUrl,
  mergeTargets,
  parseArgs,
  selectTargets,
  urlKey,
} = require("./full_crawl_lib");

assert.strictEqual(urlKey("https://example.edu/a/?utm_source=x#part"), "https://example.edu/a");
assert.strictEqual(allowedUrl("https://study.example.edu/master/x", ["example.edu"]), true);
assert.strictEqual(allowedUrl("https://mastersportal.com/x", ["mastersportal.com"]), false);
assert.strictEqual(hashUrl("https://example.edu/a"), hashUrl("https://example.edu/a/#x"));

const merged = mergeTargets(
  [{ universityId: "u_a", name: "A", officialDomains: ["a.edu"], catalogPages: ["https://a.edu/one"] }],
  [[{ universityId: "u_a", indexUrl: "https://a.edu/all", catalogPages: ["https://a.edu/two"] }]],
);
assert.deepStrictEqual(merged[0].catalogPages, ["https://a.edu/one", "https://a.edu/two"]);
assert.deepStrictEqual(merged[0].officialDomains, ["a.edu"]);

const options = parseArgs(["--worker-count", "2", "--worker-index", "1", "--limit", "2"]);
const selected = selectTargets([{ universityId: "0" }, { universityId: "1" }, { universityId: "2" }, { universityId: "3" }, { universityId: "4" }], options);
assert.deepStrictEqual(selected.map(item => item.universityId), ["1", "3"]);

console.log("[full-crawl-lib-test] passed");
