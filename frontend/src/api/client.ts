export type UserRole = 'admin' | 'freelancer' | 'unknown'

export interface AuthUser {
  id: number
  email: string
  role: UserRole
}

export interface Company {
  id: number
  name: string
  billing_email: string
}

export interface FreelancerProfile {
  id: number
  name: string
}

export interface Contract {
  id: number
  company: Company
  freelancer: FreelancerProfile
  daily_rate: string
  start_date: string
  end_date: string
  status: 'active' | 'closed'
}

export interface TimesheetEntry {
  id: number
  contract: number
  contract_id: number
  date: string
  hours: string
  status: 'draft' | 'submitted' | 'approved' | 'rejected'
  rejection_reason: string | null
}

export interface BillingRunResult {
  run_id: number
  invoices_generated: number
  status: string
}

export interface Invoice {
  id: string | number
  [key: string]: unknown
}

export interface WebhookEndpoint {
  id: string | number
  url: string
  active: boolean
}

function getToken(): string | null {
  return localStorage.getItem('token')
}

function authHeaders(): HeadersInit {
  const token = getToken()
  return token ? { Authorization: `Token ${token}` } : {}
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
      ...(options.headers ?? {}),
    },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    const err = new ApiError(res.status, body)
    throw err
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

export class ApiError extends Error {
  status: number
  data: Record<string, unknown>

  constructor(status: number, data: Record<string, unknown>) {
    super(`HTTP ${status}`)
    this.status = status
    this.data = data
  }
}

export const api = {
  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'POST', body: JSON.stringify(body) }),
  get: <T>(path: string) => request<T>(path),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}
