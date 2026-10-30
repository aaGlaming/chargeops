<script setup lang="ts">
import { reactive, shallowRef } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { login } from '../api/auth'
import { getApiError } from '../api/http'
import { useAuth } from '../stores/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuth()
const loading = shallowRef(false)
const form = reactive({ username: '', password: '' })

async function submit() {
  if (!form.username || form.password.length < 10) {
    ElMessage.warning('请输入用户名和至少 10 位密码。')
    return
  }
  loading.value = true
  try {
    const response = await login(form.username, form.password)
    auth.setSession(response.access_token, response.user)
    await router.replace(typeof route.query.redirect === 'string' ? route.query.redirect : '/dashboard')
  } catch (error) {
    const detail = getApiError(error)
    ElMessage.error(detail.traceId ? `${detail.message}（trace_id: ${detail.traceId}）` : detail.message)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-visual">
      <div class="visual-grid" />
      <div class="visual-content">
        <div class="brand-mark brand-mark--large">C</div>
        <p class="visual-kicker">CHARGEOPS / DECISION INTELLIGENCE</p>
        <h1>让每一个充电站决策，<br /><span>都有数据和证据支撑。</span></h1>
        <p class="visual-description">从公开站点数据、运营指标到政策知识库，统一沉淀为可追溯的选址与扩容工作台。</p>
      </div>
    </section>
    <section class="login-panel">
      <div class="login-card">
        <span class="eyebrow">WELCOME BACK</span>
        <h2>登录 ChargeOps</h2>
        <p class="login-hint">使用平台账号进入决策工作台。</p>
        <el-form label-position="top" @submit.prevent="submit">
          <el-form-item label="用户名">
            <el-input v-model="form.username" size="large" placeholder="请输入用户名" autocomplete="username" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input v-model="form.password" size="large" type="password" show-password placeholder="请输入密码" autocomplete="current-password" @keyup.enter="submit" />
          </el-form-item>
          <el-button class="login-submit" type="primary" size="large" :loading="loading" @click="submit">进入工作台</el-button>
        </el-form>
        <div class="login-footer"><span class="status-dot" /> 连接到 ChargeOps API</div>
      </div>
    </section>
  </main>
</template>

