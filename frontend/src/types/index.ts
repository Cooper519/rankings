export interface RankingEntry {
  rank: number
  universityId: string
  name: string
  country: string
  score?: number | null
  year: number
}

export interface University {
  id: string
  name: { en: string; zh?: string }
  country: string
  region: string
  website: string
  subjects: string[]
  sources: string[]
}

export interface Deadline {
  round: string
  date: string // ISO date
  applicantGroup?: 'EU' | 'Non-EU' | 'All' | 'Unknown'
}

export interface Requirements {
  gpa?: string | null
  ielts?: string | null
  toefl?: string | null
  language?: string | null
  academic?: string | null
}

export interface Program {
  id: string
  universityId: string
  subject: string
  dept: string
  program: string
  deadlines: Deadline[]
  materials: string[]
  requirements: Requirements
  sourceUrl: string
  verified: boolean
  updatedAt: string
  deadlineReviewed?: boolean
  evidenceUrls?: string[]
  fieldSources?: {
    deadlines?: string[]
    materials?: string[]
    requirements?: string[]
  }
  applicationWindows?: Deadline[]
}

export type CaptureStatus = 'captured' | 'checked-no-program' | 'blocked' | 'needs-review' | 'pending'

export interface CaptureFieldCoverage {
  coveredCount?: number
  coverageRate?: number
}

export interface CaptureSchool {
  canonicalId: string
  name: string
  country: string
  mainlandChina: boolean
  rankingSources: RankingSource[]
  ranks: Partial<Record<RankingSource, { rank: number; score?: number | null; year?: number }>>
  captureStatus: CaptureStatus
  goalCategory: string
  officialVerificationStatus?: string | null
  officialReasonCodes: string[]
  raw: {
    manifestCount: number
    programCandidates: number
    programCaptured: number
    programBlocked: number
    programErrors: number
  }
  engineeringAudit: {
    top500: boolean
    programCount: number
    coverage: Record<string, CaptureFieldCoverage>
    sourceUrlCompleteCount: number
  }
}

export interface CaptureReport {
  schemaVersion: number
  generatedAt: string
  scope: {
    rankingSources: RankingSource[]
    rankingRowLimit: number
    entityDefinition: string
    mainlandChinaPolicy: string
    sourceOfTruth: string
  }
  summary: {
    schools: number
    statusCounts: Partial<Record<CaptureStatus, number>>
    rawProgramCandidates: number
    rawProgramCaptured: number
    mainlandChinaSchools: number
    applicationAudit?: {
      top500EngineeringUniversityCount?: number
      top500EngineeringProgramCount?: number
      coverage?: Record<string, CaptureFieldCoverage>
    }
  }
  sourceFiles: {
    goalCoverage: string
    applicationAudit: string
    rankings: Record<string, string>
  }
  schools: CaptureSchool[]
}

export interface UniversityAliases {
  version: number
  generatedAt: string
  canonicalById: Record<string, string>
  reasonById: Record<string, string>
}

export type CoverageStatus = 'pending' | 'partial' | 'extracted' | 'verified'

export interface ProgramCoverage {
  universityId: string
  name: string
  country: string
  region: string
  status: CoverageStatus
  programCount: number
  deadlineCount: number
  requirementCount: number
  verifiedCount: number
  completeness: number
  officialDomains: string[]
  indexUrl: string
  updatedAt: string
}

export type Feature2CoverageStatus = 'covered' | 'missing'

export interface Feature2CoverageSelection {
  source: RankingSource
  rowIndex: number
  displayedRank: number
  year: number
}

export interface Feature2CoverageSchool {
  canonicalId: string
  name: string
  country: string
  rankingSources: RankingSource[]
  selections: Feature2CoverageSelection[]
  coverageStatus: Feature2CoverageStatus
  urlCount: number
  urls: string[]
  rankingUniversityIds?: string[]
}

export interface Feature2CoverageScope {
  rankingSources: RankingSource[]
  rankingRowLimit: number
  selectionBasis: string
  mainlandChinaInstitutionsExcluded: boolean
  hongKongAndMacauIncluded: boolean
  coverageDefinition: string
  requirementsComplete: boolean
}

export interface Feature2CoverageSummary {
  schools: number
  coveredSchools: number
  missingSchools: number
  coveragePercent: number
  recordsInFile: number
  officialUrlAssignments: number
  uniqueOfficialUrls: number
}

export interface Feature2Coverage {
  schemaVersion: number
  generatedAt: string
  scope: Feature2CoverageScope
  summary: Feature2CoverageSummary
  schools: Feature2CoverageSchool[]
}

export type SchoolUrlKind = 'school-homepage' | 'official-programme-directory' | 'official-programme-index' | 'official-department'
export type SchoolUrlVerificationStatus = 'verified' | 'recorded' | 'blocked' | 'review'

export interface SchoolUrlRecord {
  canonicalId: string
  name: string
  country: string
  url: string
  urlKind: SchoolUrlKind
  verificationStatus: SchoolUrlVerificationStatus
  sourceFile: string
}

export interface SchoolUrlIndex {
  schemaVersion: number
  generatedAt: string
  summary: {
    schoolsWithUrl: number
    byUrlKind: Partial<Record<SchoolUrlKind, number>>
    byVerificationStatus: Partial<Record<SchoolUrlVerificationStatus, number>>
  }
  sourceFiles: string[]
  schools: SchoolUrlRecord[]
}

export type RankingSource = 'qs' | 'the' | 'arwu' | 'usnews' | 'csrankings'

export const RANKING_SOURCES: RankingSource[] = ['qs', 'the', 'arwu', 'usnews', 'csrankings']

/** Application flow: pending -> submitted -> result -> offer. */
export type AppStatus = 'pending' | 'submitted' | 'result' | 'offer'

export const APP_STATUSES: AppStatus[] = ['pending', 'submitted', 'result', 'offer']

export interface UserData {
  likes: string[] // university ids
  checklist: Record<string, string[]> // programId -> checked materials
  status: Record<string, AppStatus> // universityId -> application status
  settings: { language: string; sortBy: 'deadline' | 'name' | 'added' }
}
