() => {
  const base = location.pathname.replace(/\/$/, "");
  const here = location.href.split("#")[0];
  const seen = new Set();
  const out = [];
  document.querySelectorAll("a[href]").forEach(a => {
    let href = a.href || "";
    if (!href) return;
    href = href.split("#")[0];
    if (!href || href === here) return;
    let u;
    try { u = new URL(href, location.href); } catch(e) { return; }
    if (u.host !== location.host) return;
    const path = u.pathname.replace(/\/$/, "");
    if (/\/(?:research|recherche|innovation|news|actualites?|articles?|events?|webinars?|admissions?|application|application-registration|exchange|scholarships?|information-activities|how-to-register|master-theses|mobility-programmes|incoming-students|tuition-fees?|fees-and-funding|moving-to-france|current-students(?:-\d+)?|administrative-procedures|health-insurance(?:-\d+)?|banks-insurances|accommodation|sponsorship)(?:\/|$)|\/(?:[^/]*webinar[^/]*|[^/]*graduation-ceremony[^/]*|[^/]*-anniversary(?:-|\/|$))/i.test(path + "/")) return;
    // prefer sub-pages of the index path (a real programme detail page)
    const isSub = path.startsWith(base + "/") && path.length > base.length + 1;
    const txt = (a.innerText || a.textContent || "").replace(/\s+/g, " ").trim();
    if (!txt) return;
    if (seen.has(href)) return;
    const looksNav = /^(find|all|show|search|filter|home|back|next|prev|menu|login|contact|about|cookie|skip|svenska|english)/i.test(txt);
    const reM = /msc|master|magistrale|programme|program\b/i;
    const score = (isSub ? 3 : 0) + (reM.test(txt) ? 1 : 0) + (reM.test(path) ? 1 : 0) + (looksNav ? -5 : 0) + (txt.length > 8 ? 1 : 0);
    if (score <= 1) return;
    if (!isSub && !/(?:master|msc|degree-program|study-program|programme)/i.test(path + " " + txt)) return;
    // extract a clean programme name: prefer an inner heading, else first segment
    let name = txt;
    const h = a.querySelector("h1,h2,h3,h4,[class*=title],[class*=name]");
    if (h) name = (h.innerText || "").trim();
    if (!name) name = txt.split(/\n|·|–|-/)[0].trim();
    out.push({ href, text: name.slice(0,140), path, score });
    seen.add(href);
  });
  out.sort((a,b) => b.score - a.score);
  return out.slice(0, 18).map(x => ({ href: x.href, text: x.text }));
}
