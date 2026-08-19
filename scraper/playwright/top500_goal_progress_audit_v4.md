# RankingSelect Top 500 Goal Progress Audit v4

Generated: `2026-08-14T01:55:56.576483+00:00`

## Scope Validation

| Check | Observed | Expected | Pass |
|---|---:|---:|:---:|
| Ranking rows | 2000 | 2,000 | yes |
| Canonical entities | 811 | 811 | yes |
| QS rows | 500 | 500 | yes |
| THE rows | 500 | 500 | yes |
| ARWU rows | 500 | 500 | yes |
| USNEWS rows | 500 | 500 | yes |

## Entity Raw Coverage

| Category | Entities |
|---|---:|
| `existing-program-raw` | 225 |
| `existing-zero-candidates` | 3 |
| `new-program-raw` | 130 |
| `official-blocked` | 125 |
| `official-rejected` | 16 |
| `official-review` | 193 |
| `verified-zero-candidates` | 119 |

Observed mapped manifests cover **477** entities; **355** entities have at least one programme URL in the combined raw corpus.

## Candidate Capture Status

| Corpus | Total | Captured | Error | Blocked | Missing/Pending |
|---|---:|---:|---:|---:|---:|
| existing | 12161 | 11884 | 231 | 46 | 0 |
| new | 4617 | 4557 | 39 | 21 | 0 |
| combined | 16778 | 16441 | 270 | 67 | 0 |

## Application Evidence Coverage

Programme denominator: **16779** deduplicated URLs across **355** canonical entities with programme raw.

Headline figures below use direct programme evidence only. `includingShared` is shown separately because unresolved university-level pages are inferred, not project-specific.

| Evidence | Direct programmes | Direct rate | Entities any direct | Entities fully direct | Including shared programmes |
|---|---:|---:|---:|---:|---:|
| `requirements` | 8690 | 51.79% | 290 | 56 | 8690 |
| `deadline` | 3447 | 20.54% | 219 | 13 | 3447 |
| `applicationWindow` | 3681 | 21.94% | 230 | 18 | 3681 |
| `documents` | 3636 | 21.67% | 232 | 14 | 3636 |
| `language` | 5703 | 33.99% | 252 | 33 | 5703 |
| `essentialBundle` | 2883 | 17.18% | 187 | 6 | 2883 |

`essentialBundle` means requirements + deadline + applicationWindow are all evidenced for the same programme URL.

## Missing And Blocked Groups

- `existing-zero-candidates`: 3 entities
- `official-blocked`: 125 entities
- `official-rejected`: 16 entities
- `official-review`: 193 entities
- `verified-zero-candidates`: 119 entities
- Candidate-page blocked: 29 entities
- Evidence-page blocked: 9 entities
- Browser recovery queue: 151 unique tasks

## Integrity

| Corpus | Manifests | Unreadable | Missing refs | SHA samples | SHA mismatches |
|---|---:|---:|---:|---:|---:|
| existingRaw | 353 | 0 | 0 | 64 | 0 |
| newRaw | 249 | 0 | 0 | 64 | 0 |

Queue source bodies with standalone SHA manifests: 89 checked, 89 matched, 0 mismatched.

## Method Notes

- No deadline parsing, date filtering, data cleaning, manual correction, assembly, or frontend import was performed.
- Candidate status is deduplicated per canonical entity and normalized URL. Status precedence is captured > blocked > error > pending > missing.
- Programme evidence is detected only from captured raw bodies. A `sourceUrl` chain that resolves to a programme URL is direct evidence.
- Unresolved school-level evidence is excluded from direct headline coverage and retained only in the separate `includingShared` view.
- Manifest/file existence is checked across all raw manifests. SHA-256 is checked on deterministic samples after gzip decompression, matching crawler hash semantics.
