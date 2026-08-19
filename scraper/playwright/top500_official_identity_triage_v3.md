# Top 500 official identity triage v3

Read-only diagnosis of merged `review` and `rejected` official website records. No entity is upgraded, no threshold is lowered, and ROR alone remains insufficient for verification.

## Summary

- Entities: 209 (`review`: 193, `rejected`: 16)
- ROR raw closure: 248/248 hashes verified; 0 hash failures

| Group | Count | Next step |
| --- | ---: | --- |
| Auto-recoverable evidence gap | 115 | Capture the indicated multilingual, acronym/brand, or official redirect evidence and rerun the unchanged verifier. |
| Institution relationship rule required | 18 | Resolve institution grain with a reviewed sameInstitution, formerName, successorOf, systemCampus, or distinctInstitution rule before retrying identity verification. |
| ROR match missing | 36 | Review the saved ROR candidates and query variants; require a high-confidence same-country ROR identity plus intact raw and manifest evidence. |
| True identity rejection | 1 | Reject the selected ROR organization for this target and restart ROR discovery without reusing the rejected child or different institution. |
| Capture or rendering blocked | 39 | Use browser-rendered capture or an official alternate-language/homepage route; stop for CAPTCHA and retain the current review status until both identity checks pass. |

## Samples

### Auto-recoverable evidence gap (115)
- `u_central_queensland_university_cquniversity_australia` - Central Queensland University (CQUniversity Australia) (Australia); `parenthetical-acronym-or-brand`; reasons: `ror_name_not_matched`
- `u_mcmaster_university` - McMaster University (Canada); `acronym-or-brand-title`; reasons: `live_page_identity_mismatch`
- `u_beihang_university` - Beihang University (China); `multilingual-title`; reasons: `live_page_identity_mismatch`
- `u_beijing_institute_of_technology` - Beijing Institute of Technology (China); `multilingual-title`; reasons: `live_page_identity_mismatch`
- `u_beijing_normal_university` - Beijing Normal University (China); `multilingual-title`; reasons: `live_page_identity_mismatch`

### Institution relationship rule required (18)
- `u_university_of_adelaide` - University of Adelaide (Australia); `configured-non-merging-relationship`; reasons: `ror_match_missing`
- `u_northeastern_university_shenyang` - Northeastern University (Shenyang) (China); `unreviewed-campus-system-or-name-qualifier`; reasons: `ror_name_not_matched`
- `u_kazan_volga_region_federal_university` - Kazan (Volga region) Federal University (Russia); `unreviewed-campus-system-or-name-qualifier`; reasons: `ror_name_not_matched`
- `u_indiana_university` - Indiana University (United States); `configured-non-merging-relationship`; reasons: `live_page_identity_mismatch`
- `u_penn_state_main_campus` - Penn State (Main campus) (United States); `configured-non-merging-relationship`; reasons: `ror_name_not_matched`

### ROR match missing (36)
- `u_federation_university_australia` - Federation University Australia (Australia); `saved-ror-candidates-require-review`; reasons: `ror_match_missing`
- `u_university_of_newcastle` - University of Newcastle (Australia); `saved-ror-candidates-require-review`; reasons: `ror_match_missing`
- `u_university_of_south_australia` - University of South Australia (Australia); `saved-ror-candidates-require-review`; reasons: `ror_match_missing`
- `u_the_american_university_in_cairo` - The American University in Cairo (Egypt); `saved-ror-candidates-require-review`; reasons: `ror_match_missing`
- `u_the_chinese_university_of_hong_kong` - The Chinese University of Hong Kong (Hong Kong); `saved-ror-candidates-require-review`; reasons: `ror_match_missing`

### True identity rejection (1)
- `u_national_university_of_singapore` - National University of Singapore (Singapore); `selected-ror-identity-conflicts-with-target`; reasons: `ror_name_not_matched`

### Capture or rendering blocked (39)
- `u_anhui_university` - Anhui University (China); `http-error`; reasons: `live_page_http_error`
- `u_china_agricultural_university` - China Agricultural University (China); `http-error`; reasons: `live_page_http_error`
- `u_guangzhou_medical_university` - Guangzhou Medical University (China); `http-error`; reasons: `live_page_http_error`
- `u_lanzhou_university` - Lanzhou University (China); `http-error`; reasons: `live_page_http_error`
- `u_nanjing_normal_university` - Nanjing Normal University (China); `http-error`; reasons: `live_page_http_error`

## Guardrails

- Preserve every `originalVerificationStatus` value.
- Do not convert a multilingual/acronym/domain signal directly to `verified`; capture evidence and rerun the unchanged verifier.
- Apply only reviewed relationship rules. `successorOf`, `systemCampus`, and `distinctInstitution` remain non-merging.
- Stop for CAPTCHA or human-verification challenges.
