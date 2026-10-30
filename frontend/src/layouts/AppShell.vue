<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Aim,
  DataAnalysis,
  Document,
  Histogram,
  House,
  Location,
  Notebook,
  Operation,
  Setting,
  Tickets,
  TrendCharts,
  UploadFilled,
} from '@element-plus/icons-vue'
import AppSidebar from '../components/layout/AppSidebar.vue'
import AppTopbar from '../components/layout/AppTopbar.vue'
import Breadcrumbs from '../components/layout/Breadcrumbs.vue'
import { useAuth } from '../stores/auth'
import { useNotifications } from '../composables/useNotifications'
import type { NavigationGroup } from '../types/navigation'

const route = useRoute()
const router = useRouter()
const auth = useAuth()
const { notify } = useNotifications()
const collapsed = shallowRef(false)

const navigationGroups = computed<NavigationGroup[]>(() => {
  const groups: NavigationGroup[] = [
    {
      label: '业务概览',
      items: [{ path: '/dashboard', label: '首页', icon: House, roles: ['OPS_ANALYST', 'SITE_PLANNER', 'OPS_LEAD', 'POLICY_ADMIN', 'SYSTEM_ADMIN', 'AUDITOR'] }],
    },
    {
      label: '业务数据',
      items: [
        { path: '/imports', label: '数据导入', icon: UploadFilled, roles: ['OPS_LEAD', 'POLICY_ADMIN', 'SYSTEM_ADMIN'] },
        { path: '/stations', label: '站点', icon: Location, roles: ['OPS_ANALYST', 'SITE_PLANNER', 'OPS_LEAD', 'SYSTEM_ADMIN', 'AUDITOR'] },
        { path: '/candidates', label: '候选站点', icon: Aim, roles: ['OPS_ANALYST', 'SITE_PLANNER', 'SYSTEM_ADMIN', 'AUDITOR'] },
      ],
    },
    {
      label: '智能分析',
      items: [
        { path: '/agents/coverage', label: '覆盖缺口', icon: DataAnalysis, roles: ['OPS_ANALYST', 'SITE_PLANNER', 'SYSTEM_ADMIN'] },
        { path: '/agents/competition', label: '竞争分析', icon: TrendCharts, roles: ['OPS_ANALYST', 'SITE_PLANNER', 'SYSTEM_ADMIN'] },
        { path: '/agents/site-selection', label: '候选选址', icon: Histogram, roles: ['SITE_PLANNER', 'SYSTEM_ADMIN'] },
        { path: '/agents/expansion', label: '站点扩容', icon: Operation, roles: ['OPS_LEAD', 'SITE_PLANNER', 'SYSTEM_ADMIN'] },
        { path: '/agents/policy', label: '政策匹配', icon: Tickets, roles: ['POLICY_ADMIN', 'SITE_PLANNER', 'SYSTEM_ADMIN'] },
      ],
    },
    {
      label: '知识与运行',
      items: [
        { path: '/rag', label: 'RAG 知识库', icon: Notebook, roles: ['OPS_ANALYST', 'SITE_PLANNER', 'POLICY_ADMIN', 'SYSTEM_ADMIN', 'AUDITOR'] },
        { path: '/runs', label: '运行记录', icon: Document, roles: ['OPS_ANALYST', 'SITE_PLANNER', 'OPS_LEAD', 'POLICY_ADMIN', 'SYSTEM_ADMIN', 'AUDITOR'] },
        { path: '/audit', label: '审计日志', icon: Setting, roles: ['SYSTEM_ADMIN', 'AUDITOR'] },
      ],
    },
  ]
  const userRoles = auth.roles.value
  return groups
    .map((group) => ({ ...group, items: group.items.filter((item) => !item.roles || item.roles.some((role) => userRoles.includes(role) || userRoles.includes('SYSTEM_ADMIN'))) }))
    .filter((group) => group.items.length > 0)
})

const pageTitle = computed(() => route.meta.title || '首页')
const pageSubtitle = computed(() => route.meta.subtitle || 'ChargeOps 充电站选址与扩容决策平台')

function handleLogout() {
  auth.clearSession()
  router.push({ name: 'login' })
}

function showNotifications() {
  notify('当前没有新的待处理通知。', { title: '通知中心' })
}
</script>

<template>
  <el-container class="app-shell">
    <AppSidebar :groups="navigationGroups" :collapsed="collapsed" @select="router.push" />
    <el-container class="app-main-container">
      <AppTopbar
        :display-name="auth.displayName.value"
        :roles="auth.roles.value"
        :collapsed="collapsed"
        @toggle-sidebar="collapsed = !collapsed"
        @notification-requested="showNotifications"
        @logout="handleLogout"
      />
      <el-main class="app-content">
        <div class="content-heading">
          <div>
            <Breadcrumbs />
            <h1>{{ pageTitle }}</h1>
            <p>{{ pageSubtitle }}</p>
          </div>
          <div class="trace-chip">TRACE · {{ route.name || 'app' }}</div>
        </div>
        <RouterView v-slot="{ Component }">
          <Transition name="page-fade" mode="out-in">
            <component :is="Component" />
          </Transition>
        </RouterView>
      </el-main>
    </el-container>
  </el-container>
</template>

