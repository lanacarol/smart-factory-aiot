<script setup lang="ts">
import { ref } from 'vue'
import { formatDateTime } from '../utils/api'

export type Job = {
  id: string
  job_type: 'generate' | 'train'
  status: 'queued' | 'running' | 'succeeded' | 'failed'
  progress: number
  params: Record<string, unknown>
  message: string | null
  log_tail: string | null
  result: Record<string, unknown> | null
  requested_by: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

defineProps<{
  jobs: Job[]
  emptyText: string
}>()

const opened = ref<string | null>(null)

const STATUS: Record<Job['status'], { label: string; cls: string }> = {
  queued: { label: 'Na fila', cls: 'info' },
  running: { label: 'Executando', cls: 'warning' },
  succeeded: { label: 'Concluído', cls: 'success' },
  failed: { label: 'Falhou', cls: 'danger' }
}

function duration(job: Job) {
  if (!job.started_at) return '—'
  const end = job.finished_at ? new Date(job.finished_at) : new Date()
  const seconds = Math.max(0, Math.round((end.getTime() - new Date(job.started_at).getTime()) / 1000))
  return seconds >= 60 ? `${Math.floor(seconds / 60)} min ${seconds % 60} s` : `${seconds} s`
}

function toggle(id: string) {
  opened.value = opened.value === id ? null : id
}
</script>

<template>
  <div class="table-container">
    <table v-if="jobs.length">
      <thead>
        <tr>
          <th>Solicitado</th>
          <th>Por</th>
          <th>Situação</th>
          <th>Progresso</th>
          <th>Etapa</th>
          <th>Duração</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <template v-for="job in jobs" :key="job.id">
          <tr>
            <td>{{ formatDateTime(job.created_at) }}</td>
            <td>{{ job.requested_by || '—' }}</td>
            <td>
              <span class="badge" :class="STATUS[job.status].cls">
                {{ STATUS[job.status].label }}
              </span>
            </td>
            <td>
              <div
                class="progress"
                :class="{ done: job.status === 'succeeded', failed: job.status === 'failed' }"
              >
                <div :style="{ width: `${job.progress}%` }"></div>
              </div>
              <span class="small">{{ job.progress }}%</span>
            </td>
            <td class="muted">{{ job.message || '—' }}</td>
            <td>{{ duration(job) }}</td>
            <td>
              <button type="button" class="btn secondary small" @click="toggle(job.id)">
                {{ opened === job.id ? 'Ocultar' : 'Detalhes' }}
              </button>
            </td>
          </tr>
          <tr v-if="opened === job.id">
            <td colspan="7">
              <div class="small">Parâmetros: {{ JSON.stringify(job.params) }}</div>
              <pre class="log">{{ job.log_tail || 'Sem log ainda.' }}</pre>
            </td>
          </tr>
        </template>
      </tbody>
    </table>

    <p v-else class="muted">{{ emptyText }}</p>
  </div>
</template>
