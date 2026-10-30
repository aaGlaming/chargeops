import { computed, reactive } from 'vue'
import type { CurrentUser } from '../types/navigation'

const TOKEN_KEY = 'chargeops_access_token'
const USER_KEY = 'chargeops_current_user'

const state = reactive<{ token: string; user: CurrentUser | null }>({
  token: localStorage.getItem(TOKEN_KEY) ?? '',
  user: readUser(),
})

function readUser(): CurrentUser | null {
  const raw = localStorage.getItem(USER_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as CurrentUser
  } catch {
    localStorage.removeItem(USER_KEY)
    return null
  }
}

export function useAuth() {
  const isAuthenticated = computed(() => Boolean(state.token))
  const displayName = computed(() => state.user?.display_name || state.user?.username || '未登录')
  const roles = computed(() => state.user?.roles ?? [])

  function setSession(token: string, user: CurrentUser) {
    state.token = token
    state.user = user
    localStorage.setItem(TOKEN_KEY, token)
    localStorage.setItem(USER_KEY, JSON.stringify(user))
  }

  function clearSession() {
    state.token = ''
    state.user = null
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
  }

  function hasPermission(permission?: string) {
    if (!permission) return true
    if (roles.value.includes('ADMIN') || roles.value.includes('SYSTEM_ADMIN')) return true
    // Login returns the compact user summary. Permission details are loaded by /auth/me
    // when a page needs them, so keep navigation available until that payload is present.
    if (!state.user || !state.user.permissions) return true
    return state.user?.permissions?.includes(permission) ?? false
  }

  return { state, isAuthenticated, displayName, roles, setSession, clearSession, hasPermission }
}

export { TOKEN_KEY }

