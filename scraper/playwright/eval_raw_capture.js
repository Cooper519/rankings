() => {
  const compact = value => String(value || "").replace(/\r/g, "").replace(/[ \t]+\n/g, "\n").replace(/\n{4,}/g, "\n\n\n").trim();
  const bodyText = compact(document.body ? document.body.innerText : "");
  const main = document.querySelector("main, [role=main], article, #content, .main-content");
  const mainText = compact(main ? main.innerText : bodyText);
  const meta = {};
  document.querySelectorAll("meta[name], meta[property]").forEach(node => {
    const key = node.getAttribute("name") || node.getAttribute("property");
    const value = node.getAttribute("content");
    if (key && value && !Object.prototype.hasOwnProperty.call(meta, key)) meta[key] = value;
  });
  const headings = [...document.querySelectorAll("h1,h2,h3")]
    .map(node => compact(node.innerText || node.textContent))
    .filter(Boolean)
    .slice(0, 100);
  const jsonLd = [...document.querySelectorAll('script[type="application/ld+json"]')]
    .map(node => (node.textContent || "").trim())
    .filter(Boolean);
  const embeddedJson = [...document.scripts]
    .filter(node => node.id === "__NEXT_DATA__" || /application\/json/i.test(node.type || ""))
    .map(node => ({ id: node.id || null, type: node.type || null, text: (node.textContent || "").trim() }))
    .filter(item => item.text)
    .slice(0, 30);
  const canonical = document.querySelector('link[rel="canonical"]')?.href || null;
  const htmlLang = document.documentElement.lang || null;
  const blocked = /\b403\b|forbidden|access denied|access blocked|just a moment|cloudflare|captcha|verify you are human/i.test(bodyText.slice(0, 2500));
  const relatedSeen = new Set();
  const relatedLinks = [];
  const relatedWords = /admission|application|apply|deadline|entry requirements?|eligibility|language requirements?|documents?|how to apply|required documents?|tuition|fees/i;
  const wrongLevel = /bachelor|undergraduate|doctoral|doctorate|ph\.?d\.?/i;
  document.querySelectorAll("a[href]").forEach(anchor => {
    let url;
    try { url = new URL(anchor.href, location.href); } catch (error) { return; }
    url.hash = "";
    if (url.host !== location.host || relatedSeen.has(url.toString())) return;
    const text = compact(anchor.innerText || anchor.textContent).slice(0, 300);
    const evidence = text + " " + decodeURIComponent(url.pathname + url.search);
    if (!relatedWords.test(evidence) || wrongLevel.test(evidence)) return;
    relatedSeen.add(url.toString());
    relatedLinks.push({ url: url.toString(), text, score: (/(?:deadline|requirements?|eligibility|documents?)/i.test(evidence) ? 4 : 0) + (/(?:apply|application|admission)/i.test(evidence) ? 2 : 0) });
  });
  relatedLinks.sort((left, right) => right.score - left.score);
  return {
    requestedUrl: location.href,
    canonicalUrl: canonical,
    documentTitle: document.title || "",
    htmlLang,
    headings,
    meta,
    jsonLd,
    embeddedJson,
    relatedLinks,
    mainText,
    bodyText,
    blocked,
    textLength: bodyText.length,
  };
}
