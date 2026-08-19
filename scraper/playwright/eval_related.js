() => {
  const out = [];
  const seen = new Set();
  const here = location.href.split("#")[0];
  const re = /admission|application|apply|deadline|entry requirements?|eligibility|language requirements?|documents?|how to apply|tuition|fees/i;
  const wrongLevel = /bachelor|undergraduate|doctoral|doctorate|ph\.?d\.?/i;
  document.querySelectorAll("a[href]").forEach(a => {
    const href = (a.href || "").split("#")[0];
    const text = (a.innerText || a.textContent || "").replace(/\s+/g, " ").trim();
    const evidence = text + " " + href;
    if (!href || href === here || seen.has(href) || !re.test(evidence) || wrongLevel.test(evidence)) return;
    let url;
    try { url = new URL(href, location.href); } catch (e) { return; }
    if (url.host !== location.host) return;
    seen.add(href);
    const score = (/master|graduate/i.test(evidence) ? 4 : 0) + (/deadline|requirements?|eligibility|documents?/i.test(evidence) ? 3 : 0) + (/apply|application|admission/i.test(evidence) ? 2 : 0);
    out.push({ href, text: text.slice(0, 120), score });
  });
  out.sort((a, b) => b.score - a.score);
  return out.slice(0, 4).map(({ href, text }) => ({ href, text }));
}
