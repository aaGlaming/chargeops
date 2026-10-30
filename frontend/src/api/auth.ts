import { request } from './http'
import type { CurrentUser } from '../types/navigation'

export interface LoginResponse {
  access_token: string
  token_type: 'bearer'
  expires_in: number
  user: CurrentUser
}

export function login(username: string, password: string) {
  return request<LoginResponse>({ method: 'POST', url: '/auth/login', data: { username, password } })
}

export function getMe() {
  return request<CurrentUser>({ method: 'GET', url: '/auth/me' })
}

