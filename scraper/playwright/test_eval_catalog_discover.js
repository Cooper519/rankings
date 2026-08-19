const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const source = fs.readFileSync(__dirname + "/eval_catalog_discover.js", "utf8").trim();
assert.doesNotThrow(() => new vm.Script("(" + source + ")"));
assert(!source.includes("slice(0, 18)"), "catalogue discovery must not truncate at 18 links");
assert(!source.includes("slice(0,18)"), "catalogue discovery must not truncate at 18 links");
for (const token of ["programs:", "categories:", "pagination:", "application/ld+json", 'rel="next"']) {
  assert(source.includes(token), "missing discovery capability: " + token);
}
console.log("[catalog-discover-test] syntax and full-discovery invariants passed");
