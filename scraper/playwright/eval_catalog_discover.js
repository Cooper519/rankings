() => {
  const clean = value => String(value || "").replace(/\s+/g, " ").trim();
  const here = new URL(location.href);
  here.hash = "";
  const current = here.toString();
  const currentPath = here.pathname.replace(/\/+$/, "") || "/";
  const blockedText = clean(document.body ? document.body.innerText : "").slice(0, 2500);
  const blocked = /\b403\b|forbidden|access denied|just a moment|cloudflare|captcha|verify you are human/i.test(blockedText);
  const degreeWords = /\b(?:master(?:'s|s)?|msc|m\.sc\.?|ma\b|m\.a\.?|llm|m\.eng|meng|graduate|postgraduate|second[ -]?cycle|laurea magistrale|maestr[ií]a|m[aá]ster|magister)\b/i;
  const programmeWords = /\b(?:programme|program|degree|course|curriculum|study option|education|formation|opleiding|studiengang|studieprogram)\b/i;
  const categoryWords = /\b(?:all|find|search|explore|list|catalog(?:ue)?|faculty|faculties|school|department|subject|discipline|field|area|filter|results?)\b/i;
  // Numeric links are only pagination when the URL carries an explicit page
  // parameter. Catalogue pages often contain years or numbered programme
  // links that should remain ordinary catalogue links.
  const paginationWords = /^(?:next|previous|prev|older|newer|load more|show more|view more|more results)$/i;
  const rejectWords = /\b(?:bachelor|undergraduate|ph\.?d\.?|doctoral|doctorate|research project|news|events?|webinars?|open days?|summer schools?|continuing education|professional education|education for professionals|information activities|scholarship|tuition|fees|housing|accommodation|exchange|mobility|alumni|staff|people|vacanc|job|press|privacy|cookie|login|sign in|contact|about us)\b/i;
  const nonProgramSignal = /\b(?:open days?|summer schools?|webinars?|information activities|continuing education|education for professionals|professional education)\b/i;
  const rejectPath = /\/(?:news|events?|webinars?|research|people|staff|jobs?|vacanc(?:y|ies)|press|privacy|cookies?|login|contact|about|alumni|housing|accommodation|scholarships?|tuition-fees?|exchange|mobility|search|information-activities)(?:\/|$)/i;
  const categoryPath = /\/(?:study|studies|education|academic|programmes?|programs?|degrees?|courses?|curricul|masters?|graduate|postgraduate|facult(?:y|ies)|schools?|departments?|subjects?|disciplines?|fields?)(?:\/|$)/i;
  const programmePath = /\/(?:programmes?|programs?|degrees?|courses?|curricul(?:um|a)|study-programmes?|study-programs?|masters?|master-degree|second-cycle|laurea-magistrale)(?:\/[^/?#]+){1,}/i;
  // Official catalogues sometimes expose opaque detail routes. Keep these as
  // raw programme candidates; degree-level cleaning happens later.
  const opaqueProgrammePath = /(?:\/program\d+\.html$|\/course_of_study\/[^/?#]+$|\/oferta-de-masteres\/[^/?#]+$|\/estudio\/ver$|\/ProgramHakkinda\.php$|\/program_detay\.php$|\/lisansustu-programlari\/\d+$|\/lisans-ustu-programlar\/\d+$|\/course\/[^/?#]+$|\/degree-program\/[^/?#]+$|\/studiengaenge\/[^/?#]+-master$)/i;
  const seen = new Map();
  const listingContext = /(?:study-options|master(?:s|programme|program)?|graduate|postgraduate|degree-program|study-program|programme|programmes|courses?)/i.test(currentPath);

  const add = (rawUrl, rawText, source, element) => {
    let url;
    try {
      url = new URL(rawUrl, location.href);
    } catch (error) {
      return;
    }
    if (!/^https?:$/.test(url.protocol) || url.host !== location.host) return;
    url.hash = "";
    for (const key of [...url.searchParams.keys()]) {
      if (/^(?:utm_.+|fbclid|gclid|ref|source)$/i.test(key)) url.searchParams.delete(key);
    }
    if (url.pathname !== "/") url.pathname = url.pathname.replace(/\/+$/, "");
    const href = url.toString();
    if (href === current || /\.(?:pdf|docx?|xlsx?|pptx?|zip|jpg|jpeg|png|gif|svg)$/i.test(url.pathname)) return;
    const text = clean(rawText).slice(0, 500);
    const semantic = clean([
      text,
      element?.getAttribute?.("aria-label"),
      element?.getAttribute?.("title"),
      element?.closest?.("article,li,tr,[class*=card],[class*=result],[class*=item]")?.innerText,
      decodeURIComponent(url.pathname),
    ].filter(Boolean).join(" "));
    if (nonProgramSignal.test(semantic)) return;
    if (rejectPath.test(url.pathname) || (rejectWords.test(semantic) && !degreeWords.test(semantic))) return;

    const rel = clean(element?.getAttribute?.("rel"));
    const pageParam = [...url.searchParams.keys()].some(key => /^(?:page|p|offset|start|pageNumber|page_num)$/i.test(key));
    const pagination = rel.split(/\s+/).includes("next") || rel.split(/\s+/).includes("prev") || pageParam || paginationWords.test(text);
    const degreeHit = degreeWords.test(semantic);
    const programmeHit = programmeWords.test(semantic);
    const pathDepth = url.pathname.split("/").filter(Boolean).length;
    const currentDepth = currentPath.split("/").filter(Boolean).length;
    const opaqueDetail = opaqueProgrammePath.test(url.pathname);
    const detailPath = opaqueDetail || programmePath.test(url.pathname) || (categoryPath.test(url.pathname) && pathDepth > currentDepth);
    const categoryHit = categoryWords.test(semantic) || categoryPath.test(url.pathname);
    const elementIsResult = Boolean(element?.closest?.("article,li,tr,[class*=card],[class*=result],[class*=programme],[class*=program],[class*=course],[class*=degree],[data-program],[data-course]"));
    const hasSpecificText = text.length >= 5 && !/^(?:learn more|read more|view more|apply|admission|requirements?|deadlines?|programmes?|programs?|courses?|degrees?|study options?)$/i.test(text);

    let kind = "other";
    let score = 0;
    if (pagination) {
      kind = "pagination";
      score = 20;
    } else {
      if (degreeHit) score += 7;
      if (programmeHit) score += 4;
      if (detailPath) score += 5;
      if (elementIsResult) score += 3;
      if (pathDepth > currentDepth) score += 1;
      if (categoryHit) score += 2;
      if (/(?:apply|admission|requirement|deadline)/i.test(semantic)) score -= 3;
      if (/(?:admission|application|how.?to.?apply|requirements?)/i.test(semantic) && !degreeHit) kind = "other";
      else if (degreeHit && programmeHit && (detailPath || elementIsResult)) kind = "program";
      else if (detailPath && degreeHit) kind = "program";
      else if (opaqueDetail && hasSpecificText) kind = "program";
      else if (categoryHit && (degreeHit || programmeHit)) kind = "category";
      else if (degreeHit && pathDepth >= currentDepth) kind = "category";
      // Some official catalogues expose programme cards with opaque IDs or
      // slugs such as /en/study-options/12345. Preserve those links during
      // raw capture when the page is an unmistakable programme listing.
      else if (listingContext && elementIsResult && hasSpecificText && pathDepth > currentDepth) kind = "program";
    }
    if (kind === "other") return;
    const previous = seen.get(href);
    const item = { url: href, text, kind, score, source };
    if (!previous || previous.score < score || (previous.kind !== "program" && kind === "program")) seen.set(href, item);
  };

  document.querySelectorAll("a[href]").forEach(anchor => add(anchor.href, anchor.innerText || anchor.textContent, "anchor", anchor));
  document.querySelectorAll('link[rel="next"],link[rel="prev"]').forEach(link => add(link.href, link.rel, "link-rel", link));

  const jsonLdTypes = new Set(["Course", "EducationalOccupationalProgram", "ItemList", "CollectionPage"]);
  for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
    let data;
    try { data = JSON.parse(script.textContent || "null"); } catch (error) { continue; }
    const walk = (node, depth = 0) => {
      if (!node || depth > 12) return;
      if (Array.isArray(node)) return node.forEach(item => walk(item, depth + 1));
      if (typeof node !== "object") return;
      const types = Array.isArray(node["@type"]) ? node["@type"] : [node["@type"]];
      const relevant = types.some(type => jsonLdTypes.has(type));
      if (relevant) add(node.url || node["@id"], node.name || node.headline, "json-ld", null);
      if (node.item) walk(node.item, depth + 1);
      if (node.itemListElement) walk(node.itemListElement, depth + 1);
      if (node.mainEntity) walk(node.mainEntity, depth + 1);
      if (node.hasCourse) walk(node.hasCourse, depth + 1);
      if (node["@graph"]) walk(node["@graph"], depth + 1);
    };
    walk(data);
  }

  const items = [...seen.values()].sort((left, right) => right.score - left.score || left.url.localeCompare(right.url));
  return {
    url: location.href,
    title: document.title || "",
    blocked,
    programs: items.filter(item => item.kind === "program"),
    categories: items.filter(item => item.kind === "category"),
    pagination: items.filter(item => item.kind === "pagination"),
    counts: {
      anchors: document.querySelectorAll("a[href]").length,
      programs: items.filter(item => item.kind === "program").length,
      categories: items.filter(item => item.kind === "category").length,
      pagination: items.filter(item => item.kind === "pagination").length,
    },
  };
}
