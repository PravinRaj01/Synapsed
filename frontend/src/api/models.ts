// Response shapes for endpoints the backend has not declared response models for yet (the generated schema types
// them as `unknown`). Keep these in step with the API until the backend declares them, then delete this file.

export type Workspace = {
  id: string
  name: string
  company: string
  industry: string
  role: string
  campaigns: number
  created_at: string
}

export type Campaign = {
  id: string
  workspace_id: string
  name: string
  goal: string | null
  created_at: string
  resources: number
  staged: number
  insights: number
  themes: number
}
