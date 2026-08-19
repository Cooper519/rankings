const assert = require("assert");
const fs = require("fs");

const source = fs.readFileSync(__dirname + "/eval_extract.js", "utf8").trim();

function extract(bodyText) {
  const document = {
    body: { innerText: bodyText },
    title: "Computer Science (MSc) | Example University",
    querySelectorAll: () => [{ innerText: "Computer Science (MSc)" }],
  };
  const location = { href: "https://example.edu/program/computer-science" };
  return new Function("document", "location", "return (" + source + ");")(document, location)();
}

const result = extract("Master's Open Day on 12 February 2027. Apply for admission by 1 April 2027.");
assert.deepStrictEqual(result.deadlines, [{ round: "Application", date: "1 April 2027" }]);
const range = extract("When to apply: Rolling admission 1 October 2026–31 March 2027. Fees for non-EU/EEA students apply.");
assert.deepStrictEqual(range.deadlines, [{ round: "Rolling", date: "31 March 2027" }]);
console.log("[extract-test] event and range starts excluded, deadlines retained");
