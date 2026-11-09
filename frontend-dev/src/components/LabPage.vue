<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import JobList, { type Job } from './JobList.vue'
import { apiFetch, formatDateTime, type Role } from '../utils/api'

const props = defineProps<{
  token: string
  role: Role
}>()

const canRun = computed(() => props.role === 'admin' || props.role === 'operator')

const MODES = [
  { value: 'geral', label: 'Geral (todos os sinais)' },
  { value: 'rolamento', label: 'Rolamento (vibração)' },
  { value: 'superaquecimento', label: 'Superaquecimento (temperatura)' },
  { value: 'eletrica', label: 'Elétrica (corrente)' }
]

const form = ref({
  motors: 200,
  cycles: 5000,
  seed: 42,
  failure_rate: 70,
  failure_modes: ['geral', 'rolamento', 'superaquecimento', 'eletrica'],
  noise: 1,
  missing_percent: 1,
  outlier_percent: 0.8,
  days: 30
})

const jobs = ref<Job[]>([])
const error = ref('')
const feedback = ref('')
const sending = ref(false)

let timer: ReturnType<typeof setTimeout> | undefined
let active = true

const generateJobs = computed(() => jobs.value.filter(job => job.job_type === 'generate'))

const running = computed(() =>
  generateJobs.value.some(job => job.status === 'queued' || job.status === 'running')
)

const totalRows = computed(() => form.value.motors * form.value.cycles)

// Base atual = resultado do ultimo job de geracao concluido.
const dataset = computed(() => {
  const job = generateJobs.value.find(item => item.status === 'succeeded' && item.result)
  if (!job) return null
  const info: Record<string, any> = { ...job.result, finished_at: job.finished_at }
  return info
})

async function loadJobs() {
  try {
    const data = await apiFetch<{ jobs: Job[] }>(props.token, '/api/jobs?limit=30')
    jobs.value = data.jobs
    error.value = ''
  } catch (err) {
    error.value = (err as Error).message
  }

  if (active) {
    timer = setTimeout(loadJobs, running.value ? 2000 : 6000)
  }
}

async function submit() {
  if (!form.value.failure_modes.length) {
    feedback.value = 'Escolha pelo menos um modo de falha.'
    return
  }

  sending.value = true
  feedback.value = ''

  try {
    await apiFetch(props.token, '/api/jobs/generate', {
      method: 'POST',
      body: form.value
    })
    feedback.value = 'Job enviado para a fila q.jobs.generate.'
    clearTimeout(timer)
    loadJobs()
  } catch (err) {
    feedback.value = (err as Error).message
  } finally {
    sending.value = false
  }
}

onMounted(loadJobs)

onUnmounted(() => {
  active = false
  clearTimeout(timer)
})
</script>

<template>
  <section class="app-page">
    <header class="page-header">
      <div>
        <div class="eyebrow">Inteligência artificial</div>
        <h1>Laboratório de Dados</h1>
        <p>
          Gera a base sintética usada no treino. O pedido vai para a fila
          <code>q.jobs.generate</code> do RabbitMQ e o worker <code>ai-jobs</code> executa em segundo plano.
        </p>
      </div>
      <span class="badge" :class="running ? 'warning' : 'success'">
        {{ running ? 'Gerando dados...' : 'Worker livre' }}
      </span>
    </header>

    <p v-if="error" class="error">{{ error }}</p>

    <div class="metrics" v-if="dataset">
      <div class="metric-card">
        <span>Registros na base atual</span>
        <strong>{{ Number(dataset.rows).toLocaleString('pt-BR') }}</strong>
        <small>{{ dataset.motors }} motores × {{ dataset.cycles_per_motor }} ciclos</small>
      </div>
      <div class="metric-card">
        <span>Motores que falham no período</span>
        <strong>{{ dataset.motors_failed_in_period }}</strong>
        <small>{{ dataset.failure_rate_percent }}% configurado</small>
      </div>
      <div class="metric-card">
        <span>Modos de falha</span>
        <strong style="font-size: 16px">
          <span v-for="(qty, mode) in dataset.failure_modes" :key="mode" style="display:block">
            {{ mode }}: {{ qty }}
          </span>
        </strong>
      </div>
      <div class="metric-card">
        <span>Período simulado</span>
        <strong>{{ dataset.days }} dias</strong>
        <small>Gerada em {{ formatDateTime(dataset.finished_at) }} · {{ dataset.file_size_mb }} MB</small>
      </div>
    </div>

    <section class="panel">
      <div class="panel-heading">
        <div>
          <h2>Configurar nova base</h2>
          <p>A base nova substitui a anterior só quando a geração termina.</p>
        </div>
      </div>

      <form @submit.prevent="submit">
        <div class="form-grid">
          <label class="field">
            Motores
            <input v-model.number="form.motors" type="number" min="10" max="400" required>
            <small>10 a 400 (mínimo 10 para separar treino/validação/teste por motor)</small>
          </label>
          <label class="field">
            Ciclos por motor
            <input v-model.number="form.cycles" type="number" min="500" max="8000" step="100" required>
            <small>Total: {{ totalRows.toLocaleString('pt-BR') }} linhas</small>
          </label>
          <label class="field">
            Motores que falham (%)
            <input v-model.number="form.failure_rate" type="number" min="0" max="100" required>
            <small>Percentual que chega à falha dentro do período</small>
          </label>
          <label class="field">
            Período simulado (dias)
            <input v-model.number="form.days" type="number" min="1" max="365" required>
            <small>Define o ciclo dia/noite da temperatura ambiente</small>
          </label>
          <label class="field">
            Ruído dos sensores (×)
            <input v-model.number="form.noise" type="number" min="0" max="3" step="0.1" required>
            <small>1 = ruído padrão</small>
          </label>
          <label class="field">
            Leituras faltantes (%)
            <input v-model.number="form.missing_percent" type="number" min="0" max="20" step="0.5" required>
            <small>Sensor sem resposta (valor vazio)</small>
          </label>
          <label class="field">
            Outliers (%)
            <input v-model.number="form.outlier_percent" type="number" min="0" max="10" step="0.1" required>
            <small>Picos anômalos de vibração e temperatura</small>
          </label>
          <label class="field">
            Semente
            <input v-model.number="form.seed" type="number" min="0" max="999999" required>
            <small>Mesma semente = mesma base</small>
          </label>
        </div>

        <h3 style="margin-top: 20px">Modos de falha</h3>
        <div class="checks">
          <label v-for="mode in MODES" :key="mode.value" class="check">
            <input v-model="form.failure_modes" type="checkbox" :value="mode.value">
            {{ mode.label }}
          </label>
        </div>

        <div class="actions">
          <button class="btn" type="submit" :disabled="!canRun || sending || running">
            {{ running ? 'Aguarde o job atual' : 'Gerar base de dados' }}
          </button>
          <span v-if="!canRun" class="small">Seu perfil possui acesso somente para visualização.</span>
          <span v-if="feedback" class="feedback">{{ feedback }}</span>
        </div>
      </form>
    </section>

    <section class="panel">
      <div class="panel-heading">
        <div>
          <h2>Jobs de geração</h2>
          <p>Progresso enviado pelo worker em eventos <code>job.status.*</code>.</p>
        </div>
      </div>
      <JobList :jobs="generateJobs" empty-text="Nenhuma base gerada pela interface ainda." />
    </section>
  </section>
</template>

<style src="../styles/pages.css"></style>
