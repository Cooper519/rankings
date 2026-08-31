# Ranking snapshot inputs

Each ranking source exposes its current normalized 500-row snapshot at:

    raw/rankings/<source>/normalized.json

Supported sources are `qs`, `the`, `arwu`, `usnews`, and `csrankings`. These
files are canonical pipeline inputs. `frontend/public/data/rankings/*.json`
are generated views and must not be edited or used as scraper state.

Every row uses the frontend-compatible keys `rank`, `universityId`, `name`,
`country`, `score`, and `year`. Raw API captures may live beside the normalized
snapshot, but adapters must never overwrite historical evidence.
