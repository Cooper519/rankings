const { McpClient } = require("./mcp_client");

const targets = [
  ["aueb", "https://www.aueb.gr/en/masters"],
  ["bielefeld", "https://www.uni-bielefeld.de/studium/studienangebot/"],
  ["cvut", "https://www.cvut.cz/en/study-programmes"],
  ["tuhh", "https://www.tuhh.de/tuhh/en/studying/degree-programmes"],
  ["itu", "https://www.itu.edu.tr/en/education/graduate-programs"],
  ["ntua", "https://www.ntua.gr/en/education/postgraduate-studies"],
  ["paderborn", "https://www.uni-paderborn.de/en/studies/degree-programmes"],
  ["charles", "https://cuni.cz/UKEN-1.html"],
];

const parseResult = text => JSON.parse(String(text || "").replace(/^### Result\s*/, "").split(/\n### Ran Playwright/)[0]);
const evaluator = `() => {
  const clean = value => String(value || "").replace(/\\s+/g, " ").trim();
  return {
    url: location.href,
    title: document.title || "",
    body: clean(document.body && document.body.innerText).slice(0, 1400),
    links: [...document.querySelectorAll("a[href]")]
      .map(anchor => ({ text: clean(anchor.innerText || anchor.textContent).slice(0, 180), href: anchor.href }))
      .filter(item => /master|msc|graduate|programme|program|degree|study/i.test(item.text + " " + item.href))
      .slice(0, 100),
  };
}`;

(async () => {
  const client = new McpClient({ headless: true, timeoutMs: 60000 });
  await client.init();
  try {
    for (const [name, url] of targets) {
      try {
        await client.navigate(url);
        await client.waitFor(3);
        console.log("### " + name);
        console.log(JSON.stringify(parseResult(await client.eval(evaluator)), null, 2));
      } catch (error) {
        console.log("### " + name + " ERROR " + error.message);
      }
    }
  } finally {
    await client.close();
  }
})().catch(error => {
  console.error(error.stack || error.message);
  process.exit(1);
});
