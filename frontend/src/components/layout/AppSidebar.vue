<script setup lang="ts">
import type { NavigationGroup } from '../../types/navigation'

defineProps<{
  groups: NavigationGroup[]
  collapsed: boolean
}>()

const emit = defineEmits<{
  select: [path: string]
}>()

function handleSelect(path: string) {
  emit('select', path)
}
</script>

<template>
  <el-aside class="app-sidebar" :width="collapsed ? '72px' : '248px'">
    <div class="brand" :class="{ 'brand--collapsed': collapsed }">
      <div class="brand-mark">C</div>
      <div v-if="!collapsed" class="brand-copy">
        <strong>ChargeOps</strong>
        <span>充电站决策平台</span>
      </div>
    </div>

    <el-menu
      class="app-menu"
      :default-active="$route.path"
      :collapse="collapsed"
      :collapse-transition="false"
      router
      @select="handleSelect"
    >
      <template v-for="group in groups" :key="group.label">
        <div v-if="!collapsed" class="menu-group-label">{{ group.label }}</div>
        <el-menu-item v-for="item in group.items" :key="item.path" :index="item.path">
          <el-icon><component :is="item.icon" /></el-icon>
          <template #title>{{ item.label }}</template>
        </el-menu-item>
      </template>
    </el-menu>

    <div v-if="!collapsed" class="sidebar-footer">
      <span class="status-dot" />
      <span>API 服务在线</span>
    </div>
  </el-aside>
</template>

