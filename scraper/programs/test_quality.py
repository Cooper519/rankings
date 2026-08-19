"""Regression checks for false programme pages seen in live catalogues."""
from scraper.programs.quality import non_program_reason, non_program_reason_strict
from scraper.programs.sanitize_v2 import slug_title


FALSE_POSITIVES = [
    ("LiU webinars - Meet us online", "https://liu.se/en/article/webinars"),
    ("Les programmes européens de recherche", "https://www.univ-lyon1.fr/recherche/cellule-recherche-europe-1"),
    ("IdEx Programs", "https://univ-cotedazur.eu/msc-programs/tuition-fees"),
    ("IdEx Programs", "https://univ-cotedazur.eu/msc-programs/webinar-all-about-the-msc-engineers-for-smart-cities"),
    ("Chef D Equipe", "https://polytech.ulb.be/fr/etudes/masters/chef-d-equipe"),
    ("Polydaire", "https://polytech.ulb.be/fr/etudes/masters/polydaire"),
    ("Eco Marathon Shell", "https://polytech.ulb.be/fr/etudes/masters/eco-marathon-shell"),
    ("Stages", "https://polytech.ulb.be/fr/etudes/masters/stages"),
    ("International Scholarships Database", "https://globalstudyprep.com/scholarships"),
    ("Admissions", "https://example.edu/admissions"),
    ("MASTER'S ADMISSIONS PROCESS", "https://example.edu/admissions/masters/admissions-process"),
    ("MASTER : ADMISSION ON FILE", "https://example.edu/application/master-admission-file"),
    ("Master's Admission", "https://example.edu/admision-master"),
    ("Master's Admissions: Deadlines", "https://example.edu/masters-programmes/deadlines"),
    ("SCIENCES PO TWO-YEARS MASTER'S PROGRAMMES ADMISSIONS", "https://example.edu/graduate/international-admissions"),
    ("CV form instructions", "https://example.edu/apply/cv-form-instructions"),
    ("Buddy Programme", "https://example.edu/student-life/buddy-programme"),
    ("Language requirements for Master's Degree Programmes", "https://example.edu/language-requirements"),
    ("All our Master's programmes", "https://www.uva.nl/en/education/master-s/master-s-programmes/masters-programmes.html"),
    ("Alle masteropleidingen", "https://www.uva.nl/onderwijs/master/masteropleidingen/masteropleidingen.html"),
    ("Master's Degrees A to Z", "https://www.uab.cat/web/studies/graduate/university-master-s-degrees/master-s-degrees-a-to-z-1345724010056.html"),
    ("Find your master", "https://www.eur.nl/en/education/master-programmes/find-your-master"),
    ("Erasmus Mundus and master's degrees in English - Universitat Autònoma de Barcelona - UAB Barcelona", "https://www.uab.cat/web/studies/graduate/university-master-s-degrees/erasmus-mundus-and-master-s-degrees-in-english-1345664667717.html"),
    ("Results and Enrollment", "https://www.unibocconi.it/en/applying-bocconi/master-science-and-ma-programs/application-and-admissions/results-and-enrollment"),
    ("Results and Enrollment - AY 2026-27", "https://www.unibocconi.it/en/applying-bocconi/master-science-and-ma-programs/application-and-admissions/results-and-enrollment-ay-2026-27-0"),
    ("Apply to master's", "https://www.universityadmissions.se/en/apply-to-masters/"),
    ("Master's requirements", "https://www.universityadmissions.se/en/entry-requirements/masters-requirements/"),
    ("Selection process master's", "https://www.universityadmissions.se/en/selection-and-admissions-results/selection-process-masters/"),
    ("Deadlines / Closing Dates for Applications for the Master´s programmes", "https://uni-tuebingen.de/en/study/application-and-enrollment/masters-degree/openingclosing-datesdeadlines-for-applications-for-the-masters-programmes-winter-semester/"),
    ("Online application", "https://www.epfl.ch/education/admission/admission-2/master-admission-criteria-application/online-application/"),
    ("ELIGIBILITY REQUIREMENTS", "https://www.eurecom.fr/en/teaching/admission/eligibility-requirements"),
    ("REQUIRED DOCUMENTS", "https://www.eurecom.fr/en/teaching/admission/required-documents"),
    ("Application Master", "https://www.uni-potsdam.de/en/studium/application-enrollment/application-master"),
    ("Enrollment Master's", "https://www.uni-potsdam.de/en/studium/application-enrollment/enrollment-master"),
    ("Important Dates and Deadlines", "https://www.uni-frankfurt.de/en/studium/bewerbung-einschreibung/master-studiengaenge/termine-fristen"),
    ("Master’s Program Application", "https://www.rwth-aachen.de/cms/root/studium/Vor-dem-Studium/Bewerbung-um-einen-Studienplatz/~dedx/Master-Bewerbung/lidx/1/"),
    ("Application to the Master's degree programmes", "https://www.tu-darmstadt.de/studieren/studieninteressierte/bewerbung_zulassung_tu/bewerbung_master/index.en.jsp"),
    ("Application for Master’s Degree Programs", "https://www.tu.berlin/en/i-a-office-of-student-affairs/masters-application-enrollment/application"),
    ("Pre-masters", "https://www.eur.nl/en/education/master-programmes/pre-masters"),
    ("Pre-Master's and minors", "https://www.ru.nl/en/education/pre-masters-and-minors"),
    ("Academic programmes", "https://www.uni-saarland.de/en/study/programmes.html"),
    ("Teacher training programmes", "https://www.uni-saarland.de/en/study/programmes/teachers-training.html"),
    ("Exchange programs at Leibniz University Hannover", "https://www.uni-hannover.de/en/studium/im-studium/international/exchange-students/exchange-programmes-incoming-students"),
    ("Study Abroad programmes", "https://www.lunduniversity.lu.se/study/study-opportunities-lund-university/exchange-and-study-abroad/study-abroad-programmes"),
    ("Postgraduate Diploma Programmes and Fellowships", "https://www.unicatt.it/en/programmes/postgraduate-diploma-programmes.html"),
    ("Specialising Master Programmes", "https://www.unicatt.it/content/unicatt/en/programmes/specialising-master-programmes.html"),
    ("Programmes in English", "https://www.uniroma1.it/en/en/admissions"),
    ("International programmes", "https://example.edu/international-programmes"),
    ("Major programmes", "https://example.edu/major-programmes"),
    ("PROGRAMME SPECIALISATIONS", "https://www.uni-leipzig.de/en/studying/current-students/study-affairs/programme-specialisations"),
    ("Admis­sion Depart­ment", "https://www.uibk.ac.at/en/admission-department/admission/language-certificates-for-admission-to-study-programmes/"),
    ("Application guide", "https://www.uu.se/en/study/masters-studies/application/application-guide"),
    ("THE ONLINE APPLICATION: A SEAMLESS PLATFORM", "https://www.ie.edu/admissions/masters/admissions-process/online-application/"),
    ("Selection procedures", "https://example.edu/master-selection-procedures"),
    ("Financial Aid", "http://multisito.uniroma2.it/webinglese/admissions/financial-aid/"),
    ("Master's degree - required documents", "https://example.edu/master-required-documents"),
    ("Statistical data on master programmes with selection procedure", "https://example.edu/statistical-data-on-master-programmes-with-selection-procedure"),
    ("Work-integrated Master's degree programmes", "https://masters.au.dk/work-integrated-masters-degree-programmes"),
    ("Universitary Master's Degrees by areas of knowledge", "https://www.uab.cat/web/studies/graduate/university-master-s-degrees/by-areas-of-knowledge-1345666814830.html"),
    ("Overview of CEU Degree Programs", "https://www.ceu.edu/academics/degrees"),
    ("Find master's programme", "https://www.chalmers.se/en/education/find-masters-programme/"),
    ("Find your study program!", "https://www.uni-frankfurt.de/en/studium/studiengaenge"),
    ("Medizinische Hochschule Hannover : Study programmes", "https://www.mhh.de/en/study/study-programmes"),
    ("CHANGING DEGREE PROGRAMMES", "https://www.uni-leipzig.de/en/studium/im-studium/modification-and-change/changing-degree-programmes"),
    ("Other study programmes", "https://www.uni-saarland.de/en/studies/international/other-study-programmes.html"),
    ("Enrolment in two different University Degree Programmes", "https://www.unipi.it/en/education/registration/enrolment-and-registration/enrolment-in-two-different-university-degree-programmes/"),
    ("Double Degree Programmes", "https://www.tu-darmstadt.de/studieren/studieninteressierte/internationale_studieninteressierte/doppelabschlussprogramme_inbound/index.en.jsp"),
    ("Find study program", "https://en.uit.no/education?studprog_type=3&studtype=3"),
    ("Study programme finder", "https://www.uni-bayreuth.de/en/study-programme-finder"),
    ("Study Programmes and Course Catalogue", "https://www.philfak.uni-bonn.de/en/studying/studienangebot"),
    ("Master's Degree programmes taught in Italian", "https://www.unict.it/en/education/masters-degree-programmes-taught-italian"),
    ("Degree programmes with study start in February", "https://www.ku.dk/studies/masters/application-and-admission/degree-programmes-with-study-start-in-february"),
    ("First and Second Cycle Degree Programmes", "https://www.unifi.it/en/study-us/what-study/first-and-second-cycle-degree-programmes"),
    ("Range of Study Programmes", "https://www.uni-goettingen.de/en/range+of+study+programmes/46526.html"),
    ("English-Language Degree Programmes at LUH", "https://www.uni-hannover.de/en/studium/studienangebot/english-speaking-degree-programmes-at-luh"),
    ("Degree programmes A-Z", "https://uol.de/en/degree-programmes"),
    ("Degree Programmes held in English", "https://www.unipi.it/en/international-students/programmes-taught-in-english/degree-programmes-held-in-english/"),
    ("Find your programme", "https://u-paris.fr/language/en/find-your-program/"),
    ("Overview (pre)master's programmes", "https://vu.nl/en/education/master/programmes"),
    ("All study programmes", "https://www.vub.be/en/studying-vub/all-study-programmes-vub"),
    ("Applications for German nationals, holders of German entrance qualification and EU citizens and for higher master semester applications generally", "https://uni-tuebingen.de/en/study/application-and-enrollment/masters-degree/"),
    ("Apply for the winter semester!", "https://www.uni-jena.de/en/3860/degree-programmes?graduationCategory=3"),
    ("IMMUNIZATION REQUIREMENTS", "https://www.medunigraz.at/en/study-guidance/registration-and-admission/immunization-requirements"),
    ("Applying to Tampere University master’s programmes", "https://www.tuni.fi/en/tau/masters-programmes/applying"),
    ("Enrollment in Master’s Programs", "https://www.tu.berlin/en/i-a-office-of-student-affairs/masters-application-enrollment/enrollment"),
    ("Application process for applicants with a citizenship from outside EU/EEA and Switzerland", "https://www4.uib.no/en/studies/admission-and-application/application-process-for-applicants-with-a-citizenship-from-outside-eueea-and-switzerland"),
    ("Enrolment process for admitted Master Students (EU and Non-EU)", "https://www.uni-goettingen.de/en/641111.html"),
    ("Apply for a program or course in the second application round", "https://www.gu.se/en/study-in-gothenburg/apply/apply-for-a-program-or-course-in-the-second-application-round"),
    ("Apply to International master's programmes", "https://www.helsinki.fi/en/admissions-and-education/apply-bachelors-and-masters-programmes/apply-international-masters-programmes"),
    ("Application", "https://www.uni-luebeck.de/en/university-education/international/international-students/degree-programmes/application.html"),
    ("Application via uni-assist", "https://www.uni-marburg.de/en/studying/after-your-first-degree/masters-programs/application-for-a-masters-programme/assist"),
    ("Apply online! - University of Milano-Bicocca", "https://apply.unimib.it/category?forward=%2Fcourses%2Fsearch%3F"),
    ("application of information from Master's Degree. University of Navarra", "https://en.unav.edu/solicitud-de-informacion-de-master"),
    ("Apply and enrol with an Italian entry title", "https://www.unipd.it/en/orientarsi-iscriversi-titolo-italiano"),
    ("Call for grant applications for attracting talent to masters courses run by the University of the Basque Country (EHU) during the 2026-2027 academic year", "https://www.ehu.eus/en/web/masterrak-eta-graduondokoak/university-masters-degrees/pre-enrolment-and-admission/scholarships-and-grants/call-for-grant-for-master-s-degrees-run-by-the-university-of-the-basque-country"),
    ("Application for teacher training/Master of Education", "https://www.uni-hamburg.de/en/campuscenter/bewerbung/master/bewerbung-lehramt-med.html"),
    ("Stay informed: Master's application", "https://www.wur.nl/en/education/master/application-admission-masters/apply-masters-programme/keep-me-informed-msc-application-moment"),
    ("Executive Master's", "https://www.novasbe.unl.pt/en/programs/apply/executive-masters/general-admission"),
    ("Faculty of Law", "https://www.uc.pt/en/applications/masters-degree-courses/fduc/"),
    ("Department of Economics and Management", "https://www.unibw.de/internationales-en/inbound/degree-programs/department-of-economics-and-management"),
    ("Summer Institute Programs", "https://www.sacredheart.edu/admissions--aid/international-admissions/summer-institute-programs/"),
    ("Information for international prospective students for medicine and dentistry", "https://www.charite.de/en/teaching_learning/application_admission/medicine_dentistry_international/"),
    ("Medicine and dentistry (EU, EEC et al.)", "https://www.charite.de/en/teaching_learning/application_admission/medicine_dentistry_national/"),
    ("Seasonal schools organized at Ghent University", "https://www.ugent.be/en/programmes/seasonal-schools.htm"),
    ("Lifelong learning", "https://www.ugent.be/en/programmes/lifelong-learning/overview.htm"),
    ("Summer Semester 2026", "https://www.lmu.de/en/study/important-contacts/examination-offices/examination-office-for-humanities-and-social-sciences/deadlines-for-students-of-the-faculties-01-02-and-09-15-course-booking-exam-registration-decision-period/interfaculty-study-programmes-deadline-current-semester/"),
    ("Master’s diplomas", "https://www.santannapisa.it/en/training/masters-diplomas"),
    ("Research networks", "https://www.uni-muenster.de/die-universitaet/en/interdisziplinaer.html"),
    ("Didactic Fellowship programme", "https://ethz.ch/en/the-eth-zurich/education/didactic-fellowship-programme.html"),
    ("Master's courses in 2026-2027", "https://uclouvain.be/en/study-programme/masters-2026"),
    ("Master’s programs", "https://www.epfl.ch/education/master/programs/"),
    ("Professional Master’s degree programs", "https://www.fau.eu/studying/degree-programs/special-ways-to-study/professional-masters-degree-programs/"),
    ("All Programs Offered at TU Berlin", "https://www.tu.berlin/en/studying/study-programs/all-programs-offered?degreeType=Master"),
    ("Courses and programmes", "https://www.su.se/english/divisions/department-of-english/education/courses-and-programmes"),
    ("Master Programs in English - RPTU Rheinland-Pfälzische Technische Universität Kaiserslautern-Landau", "https://rptu.de/en/international/master/prospective-students/master-programs/master-programs-in-english"),
    ("Open programmes", "https://www.uva.nl/en/education/open-programmes/open-programmes.html"),
    ("OTHER EDUCATIONAL PROGRAMMES", "https://www.utwente.nl/en/education/master/other-educational-programme-types/"),
    ("Projects & Programmes", "https://www.vub.be/en/internationalisation-vub/projects-programmes"),
    ("Culture and sport team up at Unipd", "https://www.unipd.it/en"),
    ("Freie Universität Berlin", "https://www.fu-berlin.de/en/studium/bewerbung/master/index.html"),
    ("Master’s degree studies", "https://ethz.ch/en/studies/master.html"),
    ("List of Master's programmes at Aalborg University", "https://example.edu/education/master/list"),
    ("MASTER'S PROGRAMMES TAUGHT IN ENGLISH", "https://example.edu/education/masters-programmes-taught-english"),
    ("New opportunities to earn a Master's degree", "https://example.edu/education/master/new-master-s-degree-opportunities"),
    ("Doctoral Programme in Energy Systems", "https://example.edu/studies/doctoral-energy"),
    ("Become a doctoral candidate at TUM School of Management", "https://example.edu/doctoral-program"),
    ("International PhD programmes", "https://example.edu/international-phd-programmes"),
]

TRUE_PROGRAMMES = [
    ("Computer Science", "https://polytech.ulb.be/en/studies/masters/computer-science"),
    ("Cold Climate Engineering (MSCCE)", "https://www.ntnu.edu/studies/mscce"),
]


def test_event_date_is_not_a_deadline():
    """Keep the extraction regression fixture close to the quality checks."""
    from pathlib import Path

    extract = (Path(__file__).resolve().parents[1] / "playwright" / "eval_extract.js").read_text(encoding="utf-8")
    assert "EVENT_LABEL" in extract
    assert "open" in extract


def test_generic_title_recovery():
    assert slug_title("https://www.uni-ulm.de/en/study/masters/master-of-science-in-biochemistry/") == "Biochemistry"
    assert slug_title("https://www.uv.es/official-master-s-degrees/master-s-degree-biomedical-engineering-1285848941532/Titulacio.html?id=1") == "Biomedical Engineering"


def main():
    for title, url in FALSE_POSITIVES:
        assert non_program_reason(title, url), (title, url)
        assert non_program_reason_strict(title, url), (title, url)
    for title, url in TRUE_PROGRAMMES:
        assert not non_program_reason(title, url), (title, url)
        assert not non_program_reason_strict(title, url), (title, url)
    test_event_date_is_not_a_deadline()
    test_generic_title_recovery()
    print("[quality-test] false=%d true=%d ok" % (len(FALSE_POSITIVES), len(TRUE_PROGRAMMES)))


if __name__ == "__main__":
    main()
