<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const routeName = computed(() => String(route.name || 'workspace'))
</script>

<template>
  <section class="workspace-page">
    <el-card class="workspace-card">
      <div class="workspace-icon"><el-icon :size="28"><component :is="route.meta.icon" /></el-icon></div>
      <div>
        <span class="eyebrow">{{ routeName.toUpperCase() }}</span>
        <h2>{{ route.meta.title }}工作区已就绪</h2>
        <p>此模块的业务数据、加载状态、空数据、失败和权限状态将在后续步骤接入。当前路由、角色菜单和 API 基础能力已完成。</p>
      </div>
      <div class="workspace-state"><span class="status-dot" /> 基础层已连接</div>
    </el-card>
  </section>
</template>

