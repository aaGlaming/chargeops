import { createRouter, createWebHistory } from 'vue-router'
import {
  Aim,
  DataAnalysis,
  Document,
  Histogram,
  House,
  Location,
  MapLocation,
  Notebook,
  Operation,
  Setting,
  Tickets,
  TrendCharts,
  UploadFilled,
} from '@element-plus/icons-vue'
import { useAuth } from '../stores/auth'

declare module 'vue-router' {
  interface RouteMeta {
    title: string
    subtitle?: string
    icon?: unknown
    requiresAuth?: boolean
    permission?: string
  }
}

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      redirect: '/dashboard',
      meta: { title: '首页' },
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/LoginView.vue'),
      meta: { title: '登录', requiresAuth: false },
    },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: () => import('../views/DashboardView.vue'),
      meta: { title: '首页', subtitle: '运营驾驶舱', icon: House, requiresAuth: true, permission: 'menu.dashboard' },
    },
    {
      path: '/imports',
      name: 'imports',
      component: () => import('../views/ImportView.vue'),
      meta: { title: '数据导入', subtitle: '业务数据上传、校验与批次管理', icon: UploadFilled, requiresAuth: true, permission: 'menu.imports' },
    },
    {
      path: '/regions',
      name: 'regions',
      component: () => import('../views/RegionsView.vue'),
      meta: { title: '区域分析', subtitle: '区域站点密度、连接器与覆盖摘要', icon: MapLocation, requiresAuth: true, permission: 'station.read' },
    },
    {
      path: '/stations',
      name: 'stations',
      component: () => import('../views/StationsView.vue'),
      meta: { title: '站点', subtitle: '充电站与连接器目录', icon: Location, requiresAuth: true, permission: 'station.read' },
    },
    {
      path: '/candidates',
      name: 'candidates',
      component: () => import('../views/CandidatesView.vue'),
      meta: { title: '候选站点', subtitle: '候选站点生命周期与评分', icon: Aim, requiresAuth: true, permission: 'candidate.read' },
    },
    {
      path: '/agents/coverage',
      name: 'coverage-agent',
      component: () => import('../views/WorkspaceView.vue'),
      meta: { title: '覆盖缺口', subtitle: '区域充电覆盖与缺口分析', icon: DataAnalysis, requiresAuth: true, permission: 'menu.agent.coverage' },
    },
    {
      path: '/agents/competition',
      name: 'competition-agent',
      component: () => import('../views/WorkspaceView.vue'),
      meta: { title: '竞争分析', subtitle: '周边运营商与竞争格局', icon: TrendCharts, requiresAuth: true, permission: 'menu.agent.competition' },
    },
    {
      path: '/agents/site-selection',
      name: 'site-selection-agent',
      component: () => import('../views/WorkspaceView.vue'),
      meta: { title: '候选选址', subtitle: '候选站点评分与推荐', icon: Histogram, requiresAuth: true, permission: 'menu.agent.site_selection' },
    },
    {
      path: '/agents/expansion',
      name: 'expansion-agent',
      component: () => import('../views/WorkspaceView.vue'),
      meta: { title: '站点扩容', subtitle: '容量、利用率与扩容方案', icon: Operation, requiresAuth: true, permission: 'menu.agent.expansion' },
    },
    {
      path: '/agents/policy',
      name: 'policy-agent',
      component: () => import('../views/WorkspaceView.vue'),
      meta: { title: '政策匹配', subtitle: '政策资格与补贴材料匹配', icon: Tickets, requiresAuth: true, permission: 'menu.agent.policy' },
    },
    {
      path: '/rag',
      name: 'rag',
      component: () => import('../views/WorkspaceView.vue'),
      meta: { title: 'RAG 知识库', subtitle: '政策、规范与原文证据', icon: Notebook, requiresAuth: true, permission: 'rag.read' },
    },
    {
      path: '/runs',
      name: 'runs',
      component: () => import('../views/WorkspaceView.vue'),
      meta: { title: '运行记录', subtitle: 'Agent 执行过程与结果', icon: Document, requiresAuth: true, permission: 'agent.run.read' },
    },
    {
      path: '/audit',
      name: 'audit',
      component: () => import('../views/WorkspaceView.vue'),
      meta: { title: '审计日志', subtitle: '操作、权限与人工确认记录', icon: Setting, requiresAuth: true, permission: 'audit.read' },
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/dashboard',
      meta: { title: '首页' },
    },
  ],
})

router.beforeEach((to) => {
  const auth = useAuth()
  const token = localStorage.getItem('chargeops_access_token')
  if (to.meta.requiresAuth && !token) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.meta.requiresAuth && token && to.meta.permission && !auth.hasPermission(to.meta.permission)) {
    return { name: 'dashboard' }
  }
  if (to.name === 'login' && token) {
    return { name: 'dashboard' }
  }
  return true
})

export default router

