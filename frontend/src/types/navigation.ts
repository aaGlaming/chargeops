import type { Component } from 'vue'

export type UserRole = 'OPS_ANALYST' | 'SITE_PLANNER' | 'OPS_LEAD' | 'POLICY_ADMIN' | 'SYSTEM_ADMIN' | 'AUDITOR'

export interface NavigationItem {
  path: string
  label: string
  icon: Component
  roles?: UserRole[]
}

export interface NavigationGroup {
  label: string
  items: NavigationItem[]
}

export interface CurrentUser {
  id: number
  username: string
  display_name: string
  status: string
  roles: string[]
  permissions?: string[]
}

