"""Shared semantic quality rules for programme records.

The crawler sees many pages that live below a programme catalogue but are not
degree programmes (news, webinars, tuition, student services, and so on).
These rules intentionally favour precision: rejected pages stay in the crawl
queue and can be retried with a school-specific discovery strategy.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse


JUNK_TITLE = re.compile(
    r"cookie|cookies|privacy|accessibility|homepage|navigation|404|not found|"
    r"403|forbidden|access denied|just a moment|cloudflare|"
    r"^programmes?$|^programs?$|^all programmes?$|^masters?$|^bachelors?$|"
    r"^all (?:our )?master.?s programmes?$|^alle masteropleidingen$|"
    r"^master.?s degrees a to z$|^find your master$|"
    r"^find master'?s programme$|^find your study program!?$|"
    r"^find study program$|^study programme finder$|^find your programme$|"
    r"^all study programmes?$|^other study programmes?$|"
    r"^open programmes?$|^short programmes?$|^courses and programmes$|"
    r"^projects & programmes$|^discover our programmes$|"
    r"^postgraduate diploma programmes and fellowships$|"
    r"^specialising master programmes$|^programmes in english$|"
    r"^international programmes$|^major programmes?$|^programme specialisations$|"
    r"^work-integrated master.?s degree programmes$|"
    r"^universitary master.?s degrees by areas of knowledge$|"
    r"^overview of ceu degree programs$|^overview \(pre\)master'?s programmes$|"
    r"^study programmes and course catalogue$|^range of study programmes$|"
    r"^degree programmes a-z$|^degree programmes held in english$|"
    r"^english-language degree programmes at luh$|"
    r"^master'?s courses in \d{4}-\d{4}$|"
    r"^master.?s programs?$|^master programs?$|"
    r"^master.?s degree studies$|"
    r"^master'?s programs .*university$|"
    r"^master programs in (?:english|german)\b|"
    r"^master'?s degree programs\. programs of study\.|"
    r"^masters degree - programmes$|"
    r"^master.?s degree programmes taught in italian$|"
    r"^degree programmes with study start in february$|"
    r"^first and second cycle degree programmes$|"
    r"^double degree programmes$|^changing degree programmes$|"
    r"^degree programs at graduate school$|"
    r"^all programs offered at tu berlin$|"
    r"^professional master.?s degree programs$|"
    r"^professional master'?s programmes$|^extended master'?s programs$|"
    r"^research master'?s programs$|"
    r"^interuniversity master programmes: a\.y\. \d{4}/\d{4}$|"
    r"^postgraduate and other programmes$|^other educational programmes$|"
    r"^continuing education and teacher training programmes$|"
    r"^capacity development programmes$|^funding programmes according to career level$|"
    r"^dfg programs$|^bsc programmes$|"
    r"^department of\b|^faculty of\b|^executive master.?s$|"
    r"list of master'?s programmes?|master.?s programmes taught in english|"
    r"erasmus mundus and master.?s degrees in english|"
    r"new opportunities (?:to earn (?:a )?|for )?master.?s degrees?|"
    r"^study programmes?$|^degree programmes?$|^graduate programmes?$|"
    r": study programmes?$|"
    r"^academic programmes?$|^teacher training programmes?$|"
    r"^degree programmes at\b|^international degree programmes at\b|"
    r"^overview: (?:degree and certificate|teacher education) programme|"
    r"^international study programmes?$|admission requirements?|"
    r"application procedure|how (?:and when )?to apply|tuition fees?|"
    r"applications for german nationals, holders of german entrance qualification|"
    r"entry requirements?|open day|prepare for your studies|"
    r"exchange programmes?|exchange programs?|study abroad programmes?|"
    r"summer institute programs|seasonal schools organized at|"
    r"^lifelong learning$|lmu buddy program|summer semester \d{4}|"
    r"^master.?s diplomas$|^research networks$|^didactic fellowship programme$|"
    r"continuing education programme for early career researchers|"
    r"scholarship programmes?|large-scale programmes?|"
    r"scholarships? database|"
    r"university diplomas?|specialised medical programmes?|"
    r"pre-master'?s?(?: programmes?| and minors)?|"
    r"\bwebinars?\b|graduation ceremony|\banniversary\b|"
    r"^idex programs?$|^les programmes europ(?:e|é)ens de recherche$|"
    r"^chef d[ '’]?equipe$|^polydaire$|^eco marathon shell$|^stages?$|"
    r"^current students?$|^moving to france$|^sponsorship$|^uli\.ge$|"
    r"^culture and sport team up at unipd$|^freie universit.t berlin$|"
    r"^further information$|^oferta de m.sters oficials$",
    re.I,
)

INFO_PAGE_TITLE = re.compile(
    r"^admissions?$|graduate international admissions|admissions? overview|"
    r"master['’]?\s*:\s*admission|master'?s admissions?[: ](?:process|test|deadlines)|"
    r"master'?s admission$|master'?s admissions?: deadlines|"
    r"applications? and admissions? for masters?|results of the admission procedures|"
    r"eligibility criteria|eligibility requirements?|language requirements?|proof of .*language requirements?|"
    r"cv form instructions|required documents|requirements for admission|"
    r"^master.?s degree\s*-\s*required documents$|"
    r"^master'?s requirements$|^apply to master'?s$|^selection process master'?s$|"
    r"^online application$|^the online application:.*|"
    r"^application master$|^enrollment master'?s$|^application guide$|"
    r"^application$|^application via uni-assist$|"
    r"^course selection$|^calls for applications, regulations and ranking lists$|"
    r"^apply for the winter semester!?$|^applying to .*master.?s programmes$|"
    r"^apply to international master'?s programmes$|"
    r"^enrollment in master.?s programs$|"
    r"^enrolment process for admitted master students\b|"
    r"^enrolment in two different university degree programmes$|"
    r"^apply online!.*|^course selection$|"
    r"^stay informed: master'?s application$|"
    r"^immunization requirements$|"
    r"^international educational background$|"
    r"^information for international prospective students for medicine and dentistry$|"
    r"^medicine and dentistry \(eu, eec et al\.\)$|"
    r"^admission department$|^selection procedures$|selection criteria|"
    r"^important dates and deadlines$|^results and enrollment(?: - ay \d{4}-\d{2})?$|"
    r"application deadlines|financial aid|"
    r"statistical data on master programmes with selection procedure|"
    r"^deadlines? / closing dates for applications for the master.?s programmes$|"
    r"application and admission to (?:a )?master'?s degree program|"
    r"apply to a master.?s programme at .+|"
    r"application to the master'?s degree programmes|"
    r"application for master.?s degree programs|"
    r"master.?s program application|guide to applying for a master'?s degree program|"
    r"applicants with (?:a |an )?(?:non-italian|italian) qualification|"
    r"application process for applicants with a citizenship|"
    r"apply for a program or course in the second application round|"
    r"apply and enrol with an italian entry title|"
    r"application of information from master'?s degree|"
    r"call for grant applications for attracting talent to masters courses|"
    r"application for teacher training/master of education|"
    r"applying for admission to an advanced semester|"
    r"applying for a master.?s degree program as an international student|"
    r"admission to the first subject-specific semester|"
    r"admission to (?:the )?(?:medicine and dentistry|master'?s program)|"
    r"two-years master.?s programmes admissions|"
    r"two-year master.?s programmes .*: (?:deadlines|selection criteria)|"
    r"admission to master of science programmes|"
    r"admission to master'?s degree programmes|"
    r"study orientation|buddy programme|scholarships?|full degree mobility faq|"
    r"short-term blended mobility|pre-study orientation program|"
    r"^application for international students$|^enrolment for international students$|"
    r"^required documents for international students$|^country-specific requirements$",
    re.I,
)

NON_MASTER_TITLE = re.compile(
    r"\b(?:bachelor|undergraduate|doctoral|doctorate|ph\.?d\.?)\b",
    re.I,
)

BLOCKED_PATH = re.compile(
    r"/(?:research|recherche|innovation|news|actualites?|articles?|events?|"
    r"webinars?|admissions?|application|application-registration|exchange|"
    r"scholarships?|information-activities|how-to-register|master-theses|"
    r"mobility-programmes|incoming-students|tuition-fees?|fees-and-funding|"
    r"moving-to-france|current-students(?:-\d+)?|administrative-procedures|"
    r"health-insurance(?:-\d+)?|banks-insurances|accommodation|sponsorship)"
    r"(?:/|$)",
    re.I,
)

BLOCKED_PATH_FRAGMENT = re.compile(
    r"(?:^|/)(?:webinar-|.*-webinar-|.*graduation-ceremony.*|"
    r".*-anniversary(?:-|/|$)|open-day(?:-|/|$))",
    re.I,
)

DENY_HOSTS = {
    "wikipedia.org", "mastersportal.com", "studyportals.com", "findamasters.com",
    "masterstudies.com", "university-directory.eu", "globaladmissions.com",
    "collegelearners.org", "mygermanuniversity.com", "topuniversities.com",
    "timeshighereducation.com", "usnews.com",
    "globalstudyprep.com", "mastermania.com", "globaladmissions.com",
    "standyou.com", "goaustria.org",
}


def normalize_title_text(title):
    return re.sub(r"\s+", " ", re.sub(r"[\u00ad\u200b\u200c\u200d]", "", title or "")).strip()


def source_host(url):
    try:
        host = (urlparse(url or "").hostname or "").lower()
        return host[4:] if host.startswith("www.") else host
    except ValueError:
        return ""


def denied_source(url):
    host = source_host(url)
    return any(host == item or host.endswith("." + item) for item in DENY_HOSTS)


def non_program_reason(title, source_url):
    """Return a stable rejection reason, or an empty string for a candidate."""
    clean_title = normalize_title_text(title)
    if not clean_title or len(clean_title) < 4:
        return "empty-title"
    if JUNK_TITLE.search(clean_title) or INFO_PAGE_TITLE.search(clean_title):
        return "category-or-information-page"
    if NON_MASTER_TITLE.search(clean_title):
        return "non-master-degree"
    try:
        parsed = urlparse(source_url or "")
    except ValueError:
        return "invalid-source-url"
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return "invalid-source-url"
    path = parsed.path.rstrip("/") + "/"
    if BLOCKED_PATH.search(path) or BLOCKED_PATH_FRAGMENT.search(path):
        return "non-program-path"
    if denied_source(source_url):
        return "third-party-source"
    return ""


def non_program_reason_strict(title, source_url):
    """Conservative rule used to audit historical assembled records.

    Legacy crawls used admission pages as evidence for otherwise valid degree
    names, so a blocked URL alone cannot safely delete an old record. New v2
    rows use ``non_program_reason`` before they are assembled; the formal-store
    audit only rejects an unequivocally junk title.
    """
    clean_title = normalize_title_text(title)
    if not clean_title or len(clean_title) < 4:
        return "empty-title"
    if JUNK_TITLE.search(clean_title) or INFO_PAGE_TITLE.search(clean_title):
        return "category-or-information-page"
    if NON_MASTER_TITLE.search(clean_title):
        return "non-master-degree"
    if denied_source(source_url):
        return "third-party-source"
    return ""
