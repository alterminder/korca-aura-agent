export interface ImportTeamworkFilters {
  client: string
  agent: string
  inbox: string
  search: string
  mismatch_only: boolean
  unrouted_only: boolean
  imported_after: string
}

export const EMPTY_FILTERS: ImportTeamworkFilters = {
  client: '',
  agent: '',
  inbox: '',
  search: '',
  mismatch_only: false,
  unrouted_only: false,
  imported_after: '',
}
