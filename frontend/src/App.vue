<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppShell from './layouts/AppShell.vue'

const route = useRoute()
const showShell = computed(() => route.name !== 'login')
</script>

<template>
  <AppShell v-if="showShell" />
  <RouterView v-else />
</template>

