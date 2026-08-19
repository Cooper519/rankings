"""Build a conservative university-id alias map.

Ranking providers frequently use different ids for the same institution.  The
frontend needs one canonical id so program records collected for one provider
are visible from every ranking row for that institution.

Only exact normalized-name matches within the same country and reviewed manual
groups are merged automatically.  Fuzzy matches are emitted for review but are
never merged automatically.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
DATA = ROOT / "frontend" / "public" / "data"
OUT = DATA / "university_aliases.json"
REVIEW = ROOT / "scraper" / "programs" / "university_alias_review.json"


COUNTRY_ALIASES = {
    "Hong Kong SAR": "Hong Kong",
    "China (Mainland)": "China",
    "United States of America": "United States",
    "USA": "United States",
}

# These groups were observed in the five current ranking files.  The first id
# is the canonical id and should be the most descriptive/main-ranking variant.
MANUAL_GROUPS = [
    ["u_technical_university_of_munich", "u_tu_munich"],
    ["u_university_of_munich", "u_lmu_munich"],
    ["u_delft_university_of_technology", "u_tu_delft"],
    ["u_kth_royal_institute_of_technology", "u_kth_royal_inst_of_technology", "u_royal_institute_of_technology"],
    ["u_epfl", "u_epfl_ecole_polytechnique_federale_de_lausanne", "u_swiss_federal_institute_of_technology_lausanne", "u_ecole_polytechnique_federale_of_lausanne", "u_\u00e9cole_polytechnique_f\u00e9d\u00e9rale_de_lausanne"],
    ["u_university_of_bologna", "u_alma_mater_studiorum_universit\u00e0_di_bologna"],
    ["u_university_of_southern_denmark", "u_university_of_southern_denmark_sdu"],
    ["u_university_of_ulm", "u_ulm_university"],
    ["u_university_of_bordeaux", "u_universite_de_bordeaux"],
    ["u_university_of_pavia", "u_universit\u00e0_degli_studi_di_pavia"],
    ["u_university_of_valencia", "u_universitat_de_valencia"],
    ["u_charles_university", "u_charles_university_in_prague"],
    ["u_karlsruhe_institute_of_technology_kit", "u_karlsruhe_inst_of_technology"],
    ["u_technical_university_of_denmark", "u_dtu"],
    ["u_chalmers_university_of_technology", "u_chalmersgu"],
    ["u_norwegian_university_of_science_and_technology", "u_norwegian_university_of_science_and_technology_ntnu", "u_ntnu"],
    ["u_université_libre_de_bruxelles", "u_universite_libre_de_bruxelles", "u_université_libre_de_bruxelles_ulb"],
    ["u_psl_university", "u_université_psl", "u_paris_sciences_et_lettres_psl_research_university_paris", "u_psl_research_university_paris_comue"],
    ["u_university_of_côte_dazur", "u_université_côte_dazur"],
    ['u_aix_marseille_university', 'u_university_of_aix_marseille'],
    ['u_university_of_freiburg', 'u_albert_ludwigs_universitaet_freiburg'],
    ['u_université_catholique_de_louvain_uclouvain', 'u_university_catholique_of_louvain', 'u_catholic_university_of_louvain'],
    ['u_university_of_tübingen', 'u_eberhard_karls_universität_tübingen', 'u_university_of_tuebingen'],
    ['u_eindhoven_university_of_technology', 'u_tu_eindhoven'],
    ['u_university_of_erlangen_nuremberg', 'u_friedrich_alexander_universität_erlangen_nürnberg'],
    ['u_friedrich_schiller_university_jena', 'u_friedrich_schiller_university_of_jena', 'u_university_of_jena'],
    ['u_heidelberg_university', 'u_universität_heidelberg'],
    ['u_heinrich_heine_university_of_dusseldorf', 'u_heinrich_heine_university_duesseldorf', 'u_heinrich_heine_university_düsseldorf'],
    ['u_johannes_gutenberg_university_of_mainz', 'u_university_of_mainz', 'u_johannes_gutenberg_universität_mainz'],
    ['u_university_of_würzburg', 'u_julius_maximilians_universität_würzburg', 'u_university_of_wuerzburg'],
    ['u_karlsruhe_institute_of_technology', 'u_karlsruhe_institute_of_technology_kit', 'u_kit_karlsruhe_institute_of_technology'],
    ['u_university_of_kiel', 'u_kiel_university'],
    ['u_university_of_leipzig', 'u_leipzig_university'],
    ['u_university_of_munich', 'u_ludwig_maximilians_universität_münchen'],
    ['u_universitat_politècnica_de_catalunya_barcelonatech_upc', 'u_universitat_politècnica_de_catalunya', 'u_polytechnic_univ_of_catalonia'],
    ['u_universitat_politecnica_de_valencia', 'u_polytechnic_university_of_valencia'],
    ['u_pompeu_fabra_university', 'u_universitat_pompeu_fabra_barcelona'],
    ['u_université_paris_dauphine', 'u_psl_university'],
    ['u_radboud_university_nijmegen', 'u_radboud_university'],
    ['u_ruhr_university_bochum', 'u_ruhr_universität_bochum'],
    ['u_technical_university_of_berlin', 'u_tu_berlin'],
    ['u_vienna_university_of_technology', 'u_technische_universität_wien'],
    ['u_tu_dortmund_university', 'u_tu_dortmund'],
    ['u_university_of_lisbon', 'u_universidade_de_lisboa'],
    ['u_universite_de_lorraine', 'u_university_of_lorraine'],
    ['u_university_of_konstanz', 'u_universität_konstanz'],
    ['u_university_of_mannheim', 'u_universität_mannheim'],
    ['u_university_of_münster', 'u_university_of_muenster'],
    ['u_university_of_strasbourg', 'u_université_de_strasbourg'],
    ['u_university_of_stuttgart', 'u_universität_stuttgart'],
    ['u_vita_salute_san_raffaele_university', 'u_università_vita_salute_san_raffaele'],
    ['u_vrije_universiteit_amsterdam', 'u_vu_amsterdam'],
    ['u_universiti_brunei_darussalam', 'u_universiti_brunei_darussalam_ubd'],
    ['u_university_of_barcelona', 'u_universitat_de_barcelona'],
    ['u_autonomous_university_of_barcelona', 'u_universitat_autònoma_de_barcelona_uab', 'u_universitat_autònoma_de_barcelona'],
    ['u_the_university_of_new_south_wales_unsw_sydney', 'u_unsw_sydney'],
    ['u_università_cattolica_del_sacro_cuore', 'u_catholic_university_of_sacred_heart'],
]


def ascii_text(value):
    return unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")


def normalize_name(value):
    text = ascii_text(value).lower().replace("&", " and ")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"\binst\.?\b", "institute", text)
    text = re.sub(r"\buniv\.?\b", "university", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"^the\s+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def country_key(value):
    return COUNTRY_ALIASES.get(value or "", value or "")


def find_existing_id(universities, requested):
    if requested in universities:
        return requested
    wanted = normalize_name(requested.replace("u_", "").replace("_", " "))
    matches = [uid for uid, uni in universities.items() if normalize_name(uni["name"]["en"]) == wanted]
    return matches[0] if len(matches) == 1 else None


def choose_canonical(ids, universities, program_counts):
    def score(uid):
        uni = universities[uid]
        return (
            len(uni.get("sources") or []) * 100,
            min(program_counts.get(uid, 0), 20) * 2,
            len(uni.get("name", {}).get("en", "")),
            -len(uid),
        )
    return max(ids, key=score)


def main():
    universities = json.loads((DATA / "universities.json").read_text(encoding="utf-8"))
    programs = json.loads((DATA / "programs.json").read_text(encoding="utf-8"))
    program_counts = Counter(p.get("universityId") for p in programs)

    aliases = {uid: uid for uid in universities}
    reasons = {}

    exact = defaultdict(list)
    for uid, uni in universities.items():
        key = (country_key(uni.get("country")), normalize_name(uni.get("name", {}).get("en", "")))
        exact[key].append(uid)
    for ids in exact.values():
        if len(ids) < 2:
            continue
        canonical = choose_canonical(ids, universities, program_counts)
        for uid in ids:
            aliases[uid] = canonical
            if uid != canonical:
                reasons[uid] = "exact-name-country"

    for requested_group in MANUAL_GROUPS:
        resolved = []
        for requested in requested_group:
            uid = find_existing_id(universities, requested)
            if uid and uid not in resolved:
                resolved.append(uid)
        if len(resolved) < 2:
            continue
        requested_canonical = find_existing_id(universities, requested_group[0])
        canonical = requested_canonical or choose_canonical(resolved, universities, program_counts)
        for uid in resolved:
            aliases[uid] = canonical
            if uid != canonical:
                reasons[uid] = "reviewed-manual-group"

    # Flatten aliases in case an exact group points into a reviewed group.
    for uid in list(aliases):
        seen = set()
        target = aliases[uid]
        while aliases.get(target, target) != target and target not in seen:
            seen.add(target)
            target = aliases[target]
        aliases[uid] = target

    unresolved = []
    ids = list(universities)
    for i, left in enumerate(ids):
        if aliases[left] != left:
            continue
        lu = universities[left]
        ln = normalize_name(lu["name"]["en"])
        if len(ln) < 5:
            continue
        for right in ids[i + 1:]:
            if aliases[right] != right:
                continue
            ru = universities[right]
            if country_key(lu.get("country")) != country_key(ru.get("country")):
                continue
            rn = normalize_name(ru["name"]["en"])
            ratio = SequenceMatcher(None, ln, rn).ratio()
            if ratio >= 0.9 and ln != rn:
                unresolved.append({
                    "leftId": left, "leftName": lu["name"]["en"],
                    "rightId": right, "rightName": ru["name"]["en"],
                    "country": lu.get("country", ""), "similarity": round(ratio, 3),
                })

    payload = {
        "version": 1,
        "generatedAt": date.today().isoformat(),
        "canonicalById": aliases,
        "reasonById": reasons,
    }
    OUT.write_bytes(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
    REVIEW.write_bytes(json.dumps(unresolved, ensure_ascii=False, indent=2).encode("utf-8"))
    merged = sum(1 for uid, canonical in aliases.items() if uid != canonical)
    print("[aliases] universities=%d merged-aliases=%d review-candidates=%d" % (len(universities), merged, len(unresolved)))
    print("[aliases] -> %s" % OUT)


if __name__ == "__main__":
    main()
