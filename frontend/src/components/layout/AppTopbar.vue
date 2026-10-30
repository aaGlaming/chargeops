<script setup lang="ts">
import { ArrowDown, Bell, Expand, Fold, UserFilled } from '@element-plus/icons-vue'

defineProps<{
  displayName: string
  roles: string[]
  collapsed: boolean
}>()

const emit = defineEmits<{
  toggleSidebar: []
  notificationRequested: []
  logout: []
}>()
</script>

<template>
  <el-header class="app-topbar">
    <div class="topbar-left">
      <el-button class="collapse-button" text circle @click="emit('toggleSidebar')">
        <el-icon :size="20"><Expand v-if="collapsed" /><Fold v-else /></el-icon>
      </el-button>
      <div class="topbar-context">
        <span class="eyebrow">CHARGEOPS CONTROL CENTER</span>
        <span class="environment-pill">开发环境</span>
      </div>
    </div>
    <div class="topbar-actions">
      <el-button class="notification-button" text circle @click="emit('notificationRequested')">
        <el-badge is-dot class="notification-badge">
          <el-icon :size="19"><Bell /></el-icon>
        </el-badge>
      </el-button>
      <el-dropdown trigger="click" @command="(command: string) => command === 'logout' && emit('logout')">
        <button class="user-menu" type="button">
          <el-avatar :size="32" class="user-avatar"><el-icon><UserFilled /></el-icon></el-avatar>
          <span class="user-details">
            <strong>{{ displayName }}</strong>
            <small>{{ roles[0] || '系统用户' }}</small>
          </span>
          <el-icon class="user-chevron"><ArrowDown /></el-icon>
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="logout">退出登录</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </el-header>
</template>

