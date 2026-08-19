import { useEffect, useState } from 'react'
import type {
  Feature2Coverage,
  Feature2CoverageSchool,
  Feature2CoverageSummary,
  CaptureReport,
  Program,
  ProgramCoverage,
  RankingEntry,
  RankingSource,
  University,
} from '../types'
import { RANKING_SOURCES } from '../types'
import {
  buildUniversityIndex,
  loadFeature2Coverage,
  loadCaptureReport,
  loadPrograms,
  loadProgramCoverage,
  loadRanking,
  loadUniversityAliases,
  loadUniversities,
  normalizeName,
  type UniIndex,
  type UniIndexEntry,
} from '../data/loaders'

export interface DataSource {
  unis: Record<string, University>
  rankings: Record<RankingSource, RankingEntry[]>
  programs: Program[]
  /** programs de-duplicated through canonical aliases (same sourceUrl + program name kept once) */
  uniquePrograms: Program[]
  index: UniIndex
  /** all university ids that appear on at least one ranking */
  rankedIds: Set<string>
  /** program intel grouped by university id */
  programsByUni: Record<string, Program[]>
  /** program crawl coverage, resolved through canonical university ids */
  coverageByUni: Record<string, ProgramCoverage>
  /** Feature 2 coverage document and its source metadata */
  feature2Coverage: Feature2Coverage
  /** Feature 2 coverage propagated to ranking-specific university ids */
  feature2CoverageByUni: Record<string, Feature2CoverageSchool>
  /** Feature 2 coverage summary for aggregate UI metrics */
  feature2Summary: Feature2CoverageSummary
  /** school-level raw capture status for the four top-500 rankings */
  captureReport: CaptureReport
  /** ranking-specific university id -> canonical university id */
  canonicalById: Record<string, string>
  /** ids of European-target unis (non CN/US/UK/AU/IE) that appear on rankings */
  europeIds: string[]
  ready: boolean
}

let cache: DataSource | null = null
let inflight: Promise<DataSource> | null = null

const EUROPE_REGIONS = new Set(['Western Europe', 'Northern Europe', 'Southern Europe', 'Eastern Europe'])
const EXCLUDE = new Set(['China', 'United States', 'USA', 'United Kingdom', 'Australia', 'Ireland'])

const EMPTY_FEATURE2_COVERAGE: Feature2Coverage = {
  schemaVersion: 0,
  generatedAt: '',
  scope: {
    rankingSources: [],
    rankingRowLimit: 0,
    selectionBasis: '',
    mainlandChinaInstitutionsExcluded: false,
    hongKongAndMacauIncluded: false,
    coverageDefinition: '',
    requirementsComplete: false,
  },
  summary: {
    schools: 0,
    coveredSchools: 0,
    missingSchools: 0,
    coveragePercent: 0,
    recordsInFile: 0,
    officialUrlAssignments: 0,
    uniqueOfficialUrls: 0,
  },
  schools: [],
}

const EMPTY_CAPTURE_REPORT: CaptureReport = {
  schemaVersion: 0,
  generatedAt: '',
  scope: {
    rankingSources: [],
    rankingRowLimit: 0,
    entityDefinition: '',
    mainlandChinaPolicy: '',
    sourceOfTruth: '',
  },
  summary: {
    schools: 0,
    statusCounts: {},
    rawProgramCandidates: 0,
    rawProgramCaptured: 0,
    mainlandChinaSchools: 0,
  },
  sourceFiles: { goalCoverage: '', applicationAudit: '', rankings: {} },
  schools: [],
}

function coverageNameKey(name: string): string {
  return normalizeName(name)
    .replace(/ae/g, 'a')
    .replace(/oe/g, 'o')
    .replace(/ue/g, 'u')
}

export function isEuropeTarget(u: University): boolean {
  if (EXCLUDE.has(u.country)) return false
  return EUROPE_REGIONS.has(u.region)
}

export function useData(): DataSource {
  const [data, setData] = useState<DataSource | null>(cache)
  useEffect(() => {
    if (cache) return
    if (!inflight) {
      inflight = (async () => {
        const [unis, programs, aliases, coverage, feature2Coverage, captureReport, ...rankingsArr] = await Promise.all([
          loadUniversities(),
          loadPrograms(),
          loadUniversityAliases(),
          loadProgramCoverage(),
          loadFeature2Coverage(),
          loadCaptureReport(),
          ...RANKING_SOURCES.map((s) => loadRanking(s)),
        ])
        const rankings = Object.fromEntries(
          RANKING_SOURCES.map((s, i) => [s, rankingsArr[i]]),
        ) as Record<RankingSource, RankingEntry[]>
        const canonicalById = aliases.canonicalById || {}
        const index = await buildUniversityIndex(unis, rankings, canonicalById)
        const rankedIds = new Set<string>()
        for (const s of RANKING_SOURCES) for (const e of rankings[s]) rankedIds.add(e.universityId)
        const canonicalPrograms: Record<string, Program[]> = {}
        for (const p of programs) {
          const canonicalId = canonicalById[p.universityId] || p.universityId
          ;(canonicalPrograms[canonicalId] ||= []).push(p)
        }
        const programsByUni: Record<string, Program[]> = {}
        for (const universityId of Object.keys(unis)) {
          const canonicalId = canonicalById[universityId] || universityId
          const seen = new Set<string>()
          programsByUni[universityId] = (canonicalPrograms[canonicalId] || []).filter((program) => {
            const key = `${program.sourceUrl}|${normalizeName(program.program)}`
            if (seen.has(key)) return false
            seen.add(key)
            return true
          })
        }
        const uniquePrograms: Program[] = []
        const uniqueCanonicalSeen = new Set<string>()
        for (const canonicalId of Object.keys(canonicalPrograms)) {
          if (uniqueCanonicalSeen.has(canonicalId)) continue
          uniqueCanonicalSeen.add(canonicalId)
          const groupSeen = new Set<string>()
          for (const program of canonicalPrograms[canonicalId]) {
            const key = `${program.sourceUrl}|${normalizeName(program.program)}`
            if (groupSeen.has(key)) continue
            groupSeen.add(key)
            uniquePrograms.push(program)
          }
        }
        const coverageByCanonical = Object.fromEntries(coverage.map((row) => [row.universityId, row]))
        const coverageByUni: Record<string, ProgramCoverage> = {}
        for (const universityId of Object.keys(unis)) {
          const canonicalId = canonicalById[universityId] || universityId
          const row = coverageByCanonical[canonicalId]
          if (row) coverageByUni[universityId] = row
        }
        const feature2CoverageByCanonical = Object.fromEntries(
          feature2Coverage.schools.map((row) => [row.canonicalId, row]),
        )
        const feature2CoverageByName = Object.fromEntries(
          feature2Coverage.schools
            .filter((row) => row.name)
            .map((row) => [coverageNameKey(row.name), row]),
        )
        const feature2CoverageByUni: Record<string, Feature2CoverageSchool> = {
          ...feature2CoverageByCanonical,
        }
        for (const row of feature2Coverage.schools) {
          for (const rankingUniversityId of row.rankingUniversityIds || []) {
            feature2CoverageByUni[rankingUniversityId] = row
          }
        }
        const feature2UniversityIds = new Set([
          ...Object.keys(unis),
          ...Object.keys(canonicalById),
        ])
        for (const source of RANKING_SOURCES) {
          for (const entry of rankings[source]) feature2UniversityIds.add(entry.universityId)
        }
        for (const universityId of feature2UniversityIds) {
          const canonicalId = canonicalById[universityId] || universityId
          const universityName = unis[universityId]?.name?.en || index.byId[universityId]?.name || ''
          const row = feature2CoverageByCanonical[canonicalId]
            || feature2CoverageByName[coverageNameKey(universityName)]
          if (row) feature2CoverageByUni[universityId] = row
        }
        const europeIds = Object.values(unis)
          .filter((u) => isEuropeTarget(u) && rankedIds.has(u.id))
          .map((u) => u.id)
        const ds: DataSource = {
          unis, rankings, programs, uniquePrograms, index, rankedIds, programsByUni, coverageByUni,
          feature2Coverage, feature2CoverageByUni, feature2Summary: feature2Coverage.summary, captureReport,
          canonicalById, europeIds, ready: true,
        }
        cache = ds
        return ds
      })().catch((e) => {
        inflight = null
        throw e
      })
    }
    inflight.then(setData).catch(() => {})
  }, [])
  return (
    data ?? {
      unis: {}, rankings: {} as Record<RankingSource, RankingEntry[]>,
      programs: [], uniquePrograms: [], index: { byId: {}, byName: {} } as UniIndex,
      rankedIds: new Set(), programsByUni: {}, coverageByUni: {},
      feature2Coverage: EMPTY_FEATURE2_COVERAGE, feature2CoverageByUni: {},
      feature2Summary: EMPTY_FEATURE2_COVERAGE.summary,
      captureReport: EMPTY_CAPTURE_REPORT,
      canonicalById: {}, europeIds: [], ready: false,
    }
  )
}

/** aggregate rank score across boards (lower = better); used to feature top European unis */
export function aggregateRank(entry: UniIndexEntry | undefined): number | null {
  if (!entry || entry.ranks.length === 0) return null
  const scores = entry.ranks.map((r) => r.rank)
  const sum = scores.reduce((a, b) => a + b, 0)
  return sum / scores.length
}

export { normalizeName }
