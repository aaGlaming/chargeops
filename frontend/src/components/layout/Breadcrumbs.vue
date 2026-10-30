<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const items = computed(() => {
  const title = route.meta.title || '首页'
  return title === '首页' ? ['首页'] : ['首页', title]
})
</script>

<template>
  <el-breadcrumb class="page-breadcrumb" separator="/">
    <el-breadcrumb-item v-for="item in items" :key="item">{{ item }}</el-breadcrumb-item>
  </el-breadcrumb>
</template>

