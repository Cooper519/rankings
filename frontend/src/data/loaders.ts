import type {
  Feature2Coverage,
  CaptureReport,
  DataManifest,
  Program,
  ProgramCoverage,
  RankingEntry,
  RankingSource,
  SchoolUrlIndex,
  University,
  UniversityAliases,
} from '../types'
import { RANKING_SOURCES } from '../types'

const BASE = (import.meta as any).env?.BASE_URL || '/'

export async function loadJson<T>(path: string): Promise<T> {
  const res = await fetch(BASE + path)
  if (!res.ok) throw new Error(`load ${path} failed: ${res.status}`)
  return res.json() as Promise<T>
}

export async function loadUniversities(): Promise<Record<string, University>> {
  return loadJson<Record<string, University>>('data/universities.json')
}

export async function loadRanking(source: RankingSource): Promise<RankingEntry[]> {
  return loadJson<RankingEntry[]>(`data/rankings/${source}.json`)
}

export async function loadPrograms(): Promise<Program[]> {
  return loadJson<Program[]>('data/programs.json')
}

export async function loadUniversityAliases(): Promise<UniversityAliases> {
  return loadJson<UniversityAliases>('data/university_aliases.json')
}

export async function loadProgramCoverage(): Promise<ProgramCoverage[]> {
  return loadJson<ProgramCoverage[]>('data/program_coverage.json')
}

export async function loadDataManifest(): Promise<DataManifest> {
  return loadJson<DataManifest>('data/data-manifest.json')
}

export async function loadFeature2Coverage(): Promise<Feature2Coverage> {
  return loadJson<Feature2Coverage>('data/feature2_coverage.json')
}

export async function loadCaptureReport(): Promise<CaptureReport> {
  return loadJson<CaptureReport>('data/top500_capture_report.json')
}

export async function loadSchoolUrls(): Promise<SchoolUrlIndex> {
  return loadJson<SchoolUrlIndex>('data/school_urls.json')
}

/** Normalize names for matching universities across rankings and programs. */
export function normalizeName(name: string): string {
  return (name || '')
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/\s*\(.*?\)\s*/g, ' ')      // Remove parenthetical aliases such as (MIT).
    .replace(/[^\w\s]/g, ' ')            // Remove punctuation.
    .replace(/\b(the|of|university|universite|universitat|universidad|institute|technology|technische|technical|royal|school)\b/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

export interface RankSummary {
  source: RankingSource
  rank: number
  score?: number | null
  year: number
}

export interface UniIndexEntry {
  id: string
  name: string
  country: string
  region: string
  ranks: RankSummary[]
}

export interface UniIndex {
  byId: Record<string, UniIndexEntry>
  byName: Record<string, UniIndexEntry>
}

export async function buildUniversityIndex(
  unis: Record<string, University>,
  rankings: Record<RankingSource, RankingEntry[]>,
  canonicalById: Record<string, string> = {},
): Promise<UniIndex> {
  const byId: Record<string, UniIndexEntry> = {}
  const byName: Record<string, UniIndexEntry> = {}
  const upsert = (name: string, country: string, region: string, id: string): UniIndexEntry => {
    const key = normalizeName(name)
    if (!byName[key]) {
      byName[key] = { id, name, country, region, ranks: [] }
    }
    return byName[key]
  }
  for (const u of Object.values(unis)) {
    upsert(u.name.en, u.country, u.region, u.id).id = u.id
    byId[u.id] = byName[normalizeName(u.name.en)]!
  }
  for (const s of RANKING_SOURCES) {
    for (const e of rankings[s] || []) {
      const entry = upsert(e.name, e.country, '', e.universityId)
      entry.ranks.push({ source: s, rank: e.rank, score: e.score, year: e.year })
      if (!byId[e.universityId]) byId[e.universityId] = entry
    }
  }
  // Merge alias groups so every alias id resolves to one canonical entry with the full rank set.
  const groupMembers = new Map<string, Map<string, UniIndexEntry>>()
  const allIds = new Set<string>([...Object.keys(unis), ...Object.keys(canonicalById)])
  for (const s of RANKING_SOURCES) for (const e of rankings[s] || []) allIds.add(e.universityId)
  for (const id of allIds) {
    const cid = canonicalById[id] || id
    const entry = byId[id]
    if (!entry) continue
    if (!groupMembers.has(cid)) groupMembers.set(cid, new Map())
    groupMembers.get(cid)!.set(id, entry)
  }
  for (const [cid, members] of groupMembers) {
    if (members.size < 2) continue
    const canonicalEntry = byId[cid] || members.values().next().value
    const seenSource = new Set<RankingSource>()
    const merged: RankSummary[] = []
    for (const entry of members.values()) {
      for (const r of entry.ranks) {
        if (seenSource.has(r.source)) continue
        seenSource.add(r.source)
        merged.push(r)
      }
    }
    merged.sort((a, b) => RANKING_SOURCES.indexOf(a.source) - RANKING_SOURCES.indexOf(b.source))
    canonicalEntry.ranks = merged
    for (const id of members.keys()) byId[id] = canonicalEntry
  }
  return { byId, byName }
}

/** Match programs to a target university by normalized name. */
export function programsByUniversity(
  programs: Program[],
  unis: Record<string, University>,
  targetName: string,
): Program[] {
  const t = normalizeName(targetName)
  return programs.filter((p) => {
    const uni = unis[p.universityId]
    const nm = uni ? uni.name.en : p.universityId.replace(/^u_/, '').replace(/_/g, ' ')
    return normalizeName(nm) === t
  })
}
