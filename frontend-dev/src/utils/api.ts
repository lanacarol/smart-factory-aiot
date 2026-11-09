// Chamadas a API de desenvolvimento com o token da sessao.

export const API_URL = 'http://localhost:8001'

export type Role = 'admin' | 'operator' | 'viewer'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function apiFetch<T>(
  token: string,
  path: string,
  options: { method?: string; body?: unknown } = {}
): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    method: options.method ?? 'GET',
    headers: {
      Authorization: `Bearer ${token}`,
      ...(options.body !== undefined
        ? { 'Content-Type': 'application/json' }
        : {})
    },
    body: options.body !== undefined
      ? JSON.stringify(options.body)
      : undefined,
    cache: 'no-store'
  })

  if (!response.ok) {
    let message = `Erro HTTP ${response.status}`

    if (response.status === 401) message = 'Sessão expirada. Faça login novamente.'
    if (response.status === 403) message = 'Seu perfil não tem permissão para esta ação.'

    try {
      const data = await response.json()
      if (typeof data.detail === 'string') message = data.detail
      if (Array.isArray(data.detail)) message = 'Valores inválidos no formulário.'
    } catch { /* resposta sem JSON */ }

    throw new ApiError(response.status, message)
  }

  return response.json() as Promise<T>
}

export function formatDateTime(value?: string | null) {
  if (!value) return '—'
  return new Date(value).toLocaleString('pt-BR')
}

export function formatNumber(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return value.toLocaleString('pt-BR', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  })
}
