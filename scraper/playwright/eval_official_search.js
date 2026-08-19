() => {
  const clean = value => String(value || "").replace(/\s+/g, " ").trim();
  const decodeBingUrl = value => {
    try {
      const url = new URL(value, location.href);
      if (!/(^|\.)bing\.com$/i.test(url.hostname)) return url.href;
      const encoded = url.searchParams.get("u") || "";
      if (!encoded.startsWith("a1")) return url.href;
      let payload = encoded.slice(2).replace(/-/g, "+").replace(/_/g, "/");
      while (payload.length % 4) payload += "=";
      const decoded = atob(payload);
      try {
        return decodeURIComponent(decoded);
      } catch (error) {
        return decoded;
      }
    } catch (error) {
      return String(value || "");
    }
  };

  const containers = [
    ...document.querySelectorAll("li.b_algo"),
    ...document.querySelectorAll("#b_results > li[data-bm]"),
  ];
  const seen = new Set();
  const results = [];
  for (const container of containers) {
    const anchor = container.querySelector("h2 a[href], a.tilk[href]");
    if (!anchor) continue;
    const href = decodeBingUrl(anchor.href);
    if (!/^https?:\/\//i.test(href) || seen.has(href)) continue;
    seen.add(href);
    let host = "";
    try {
      host = new URL(href).hostname.toLowerCase().replace(/^www\./, "");
    } catch (error) {}
    const snippetNode = container.querySelector(
      ".b_caption p, .b_snippet, .b_lineclamp2, [class*=snippet]",
    );
    results.push({
      title: clean(anchor.innerText || anchor.textContent).slice(0, 500),
      href,
      snippet: clean(snippetNode && (snippetNode.innerText || snippetNode.textContent)).slice(0, 1500),
      host,
      rawRank: results.length + 1,
    });
  }
  return {
    engine: "bing",
    locationHref: location.href,
    urlQuery: new URL(location.href).searchParams.get("q") || "",
    inputValue: document.querySelector("#sb_form_q")?.value || "",
    resultCount: results.length,
    results: results.slice(0, 10),
  };
}
