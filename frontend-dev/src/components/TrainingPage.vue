<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { Bar, Scatter } from 'vue-chartjs'
import {
  Chart as ChartJS,
  BarElement,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Tooltip,
  Legend
} from 'chart.js'
import JobList, { type Job } from './JobList.vue'
import { apiFetch, formatDateTime, formatNumber, type Role } from '../utils/api'

ChartJS.register(BarElement, CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend)

const props = defineProps<{
  token: string
  role: Role
}>()

type Metrics = { MAE: number; RMSE: number; R2: number }

type TargetInfo = {
  target: string
  model_type: string
  baseline_test: Metrics
  validation: Metrics
  test: Metrics
  importance: { feature: string; importance: number }[]
  pred_vs_real?: [number, number][]
}

type ModelInfo = {
  model_version: string
  trained_at: string
  dataset_rows: number
  feature_set?: string
  window?: number | null
  features: string[]
  params?: Record<string, number>
  split: Record<string, number>
  targets: Record<string, TargetInfo>
}

const TARGET_LABEL: Record<string, string> = {
  health: 'Saúde (%)',
  rul: 'Vida útil restante (ciclos)'
}

const FEATURE_LABEL: Record<string, string> = {
  cycle: 'Ciclos (contador)',
  temperature_c: 'Temperatura',
  vibration_mm_s: 'Vibração',
  current_a: 'Corrente',
  ambient_temperature_c: 'Temp. ambiente',
  humidity_percent: 'Umidade',
  running: 'Ligado',
  temperature_c_mean: 'Temperatura · média',
  temperature_c_std: 'Temperatura · desvio',
  temperature_c_trend: 'Temperatura · tendência',
  vibration_mm_s_mean: 'Vibração · média',
  vibration_mm_s_std: 'Vibração · desvio',
  vibration_mm_s_trend: 'Vibração · tendência',
  current_a_mean: 'Corrente · média',
  current_a_std: 'Corrente · desvio',
  current_a_trend: 'Corrente · tendência'
}

const canRun = computed(() => props.role === 'admin' || props.role === 'operator')

const model = ref<ModelInfo | null>(null)
const jobs = ref<Job[]>([])
const error = ref('')
const feedback = ref('')
const sending = ref(false)
const selected = ref<'health' | 'rul'>('health')

const form = ref({
  max_iter: 120,
  learning_rate: 0.08,
  max_leaf_nodes: 20,
  train_rows: 160000,
  window_features: true
})

let timer: ReturnType<typeof setTimeout> | undefined
let active = true
let lastFinished = ''

const trainJobs = computed(() => jobs.value.filter(job => job.job_type === 'train'))

const running = computed(() =>
  jobs.value.some(job => job.status === 'queued' || job.status === 'running')
)

const current = computed(() => model.value?.targets[selected.value])

function gain(info: TargetInfo) {
  // Quanto o modelo reduz o erro medio em relacao a base.
  if (!info.baseline_test.MAE) return 0
  return (1 - info.test.MAE / info.baseline_test.MAE) * 100
}

const importanceChart = computed(() => {
  const items = (current.value?.importance ?? []).slice(0, 10)
  return {
    labels: items.map(item => FEATURE_LABEL[item.feature] ?? item.feature),
    datasets: [{
      label: 'Aumento do erro ao embaralhar',
      data: items.map(item => item.importance),
      backgroundColor: '#38bdf8',
      borderRadius: 6
    }]
  }
})

const importanceOptions = {
  indexAxis: 'y' as const,
  responsive: true,
  maintainAspectRatio: false,
  plugins: { legend: { display: false } },
  scales: {
    x: { ticks: { color: '#94a3b8' }, grid: { color: '#1e293b' } },
    y: { ticks: { color: '#cbd5e1' }, grid: { display: false } }
  }
}

const scatterChart = computed(() => {
  const points = current.value?.pred_vs_real ?? []
  const max = Math.max(1, ...points.flat())
  return {
    datasets: [
      {
        label: 'Previsões (teste)',
        data: points.map(([real, pred]) => ({ x: real, y: pred })),
        backgroundColor: 'rgba(56, 189, 248, 0.55)',
        pointRadius: 3
      },
      {
        label: 'Previsão perfeita',
        data: [{ x: 0, y: 0 }, { x: max, y: max }],
        showLine: true,
        backgroundColor: '#34d399',
        borderColor: '#34d399',
        borderDash: [6, 6],
        pointRadius: 0
      }
    ]
  }
})

const scatterOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: { legend: { labels: { color: '#cbd5e1' } } },
  scales: {
    x: {
      title: { display: true, text: 'Valor real', color: '#94a3b8' },
      ticks: { color: '#94a3b8' },
      grid: { color: '#1e293b' }
    },
    y: {
      title: { display: true, text: 'Valor previsto', color: '#94a3b8' },
      ticks: { color: '#94a3b8' },
      grid: { color: '#1e293b' }
    }
  }
}

async function loadModel() {
  try {
    model.value = await apiFetch<ModelInfo>(props.token, '/api/model/info')
  } catch (err) {
    error.value = (err as Error).message
  }
}

async function loadJobs() {
  try {
    const data = await apiFetch<{ jobs: Job[] }>(props.token, '/api/jobs?limit=30')
    jobs.value = data.jobs
    error.value = ''

    // Recarrega as metricas quando um treino termina.
    const finished = data.jobs.find(job => job.job_type === 'train' && job.status === 'succeeded')
    if (finished && finished.id !== lastFinished) {
      if (lastFinished) loadModel()
      lastFinished = finished.id
    }
  } catch (err) {
    error.value = (err as Error).message
  }

  if (active) {
    timer = setTimeout(loadJobs, running.value ? 2000 : 6000)
  }
}

async function submit() {
  sending.value = true
  feedback.value = ''

  try {
    await apiFetch(props.token, '/api/jobs/train', { method: 'POST', body: form.value })
    feedback.value = 'Treino enviado para a fila q.jobs.train. O modelo novo entra em uso sozinho ao terminar.'
    clearTimeout(timer)
    loadJobs()
  } catch (err) {
    feedback.value = (err as Error).message
  } finally {
    sending.value = false
  }
}

onMounted(() => {
  loadModel()
  loadJobs()
})

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
        <h1>Treinamento</h1>
        <p>
          Modelos de regressão (HistGradientBoosting) para saúde e vida útil restante.
          Treino em segundo plano pela fila <code>q.jobs.train</code>; a inferência troca de modelo sem reiniciar.
        </p>
      </div>
      <span v-if="model" class="badge info">Em uso: versão {{ model.model_version }}</span>
    </header>

    <p v-if="error" class="error">{{ error }}</p>

    <template v-if="model">
      <div class="metrics">
        <div class="metric-card">
          <span>Versão em uso</span>
          <strong class="blue">{{ model.model_version }}</strong>
          <small>Treinada em {{ formatDateTime(model.trained_at) }}</small>
        </div>
        <div class="metric-card">
          <span>Atributos</span>
          <strong style="font-size: 20px">
            {{ model.feature_set === 'window' ? `Janelas do passado (${model.window})` : 'Leituras instantâneas' }}
          </strong>
          <small>{{ model.features.length }} variáveis de entrada</small>
        </div>
        <div class="metric-card">
          <span>Base de treino</span>
          <strong>{{ model.dataset_rows.toLocaleString('pt-BR') }}</strong>
          <small>
            Divisão por motor: {{ model.split.train_motors }} treino ·
            {{ model.split.validation_motors }} validação · {{ model.split.test_motors }} teste
          </small>
        </div>
        <div v-for="(info, name) in model.targets" :key="name" class="metric-card">
          <span>{{ TARGET_LABEL[name] ?? name }} · R² no teste</span>
          <strong :class="info.test.R2 >= 0.9 ? 'green' : info.test.R2 >= 0.7 ? 'yellow' : 'red'">
            {{ formatNumber(info.test.R2, 3) }}
          </strong>
          <small>Erro médio {{ formatNumber(gain(info), 0) }}% menor que a base</small>
        </div>
      </div>

      <section class="panel">
        <div class="panel-heading">
          <div>
            <h2>Métricas no conjunto de teste</h2>
            <p>
              MAE = erro médio · RMSE = pune mais os erros grandes · R² perto de 1 é bom.
              A “base” prevê sempre a média: o modelo só vale se for bem melhor que ela.
            </p>
          </div>
        </div>
        <div class="table-container">
          <table>
            <thead>
              <tr>
                <th>Modelo</th>
                <th>MAE</th>
                <th>RMSE</th>
                <th>R²</th>
                <th>MAE validação</th>
                <th>MAE da base</th>
                <th>R² da base</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(info, name) in model.targets" :key="name">
                <td><strong>{{ TARGET_LABEL[name] ?? name }}</strong></td>
                <td>{{ formatNumber(info.test.MAE) }}</td>
                <td>{{ formatNumber(info.test.RMSE) }}</td>
                <td>{{ formatNumber(info.test.R2, 3) }}</td>
                <td>{{ formatNumber(info.validation.MAE) }}</td>
                <td class="muted">{{ formatNumber(info.baseline_test.MAE) }}</td>
                <td class="muted">{{ formatNumber(info.baseline_test.R2, 3) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <div class="actions" style="margin: 0 0 16px">
        <button
          v-for="(label, name) in TARGET_LABEL"
          :key="name"
          type="button"
          class="btn small"
          :class="selected === name ? '' : 'secondary'"
          @click="selected = name as 'health' | 'rul'"
        >
          {{ label }}
        </button>
      </div>

      <div class="grid-2" style="margin-bottom: 24px">
        <section class="panel">
          <h2>Previsto × real</h2>
          <p class="muted">300 motores-ciclo do conjunto de teste. Quanto mais perto da linha, melhor.</p>
          <div v-if="current?.pred_vs_real?.length" class="chart-box">
            <Scatter :data="scatterChart" :options="scatterOptions" />
          </div>
          <p v-else class="note" style="margin-top: 14px">
            Este modelo foi treinado antes de o gráfico existir. Treine uma nova versão para vê-lo.
          </p>
        </section>

        <section class="panel">
          <h2>Importância das variáveis</h2>
          <p class="muted">Quanto o erro aumenta ao embaralhar cada variável (permutação).</p>
          <div class="chart-box">
            <Bar :data="importanceChart" :options="importanceOptions" />
          </div>
        </section>
      </div>
    </template>

    <section class="panel">
      <div class="panel-heading">
        <div>
          <h2>Treinar nova versão</h2>
          <p>Usa a base atual do Laboratório de Dados. Separação treino/validação/teste por motor.</p>
        </div>
      </div>

      <form @submit.prevent="submit">
        <div class="form-grid">
          <label class="field">
            Iterações (árvores)
            <input v-model.number="form.max_iter" type="number" min="20" max="400" required>
            <small>20 a 400</small>
          </label>
          <label class="field">
            Taxa de aprendizado
            <input v-model.number="form.learning_rate" type="number" min="0.01" max="0.5" step="0.01" required>
            <small>0,01 a 0,5</small>
          </label>
          <label class="field">
            Folhas por árvore
            <input v-model.number="form.max_leaf_nodes" type="number" min="8" max="64" required>
            <small>8 a 64</small>
          </label>
          <label class="field">
            Linhas de treino
            <input v-model.number="form.train_rows" type="number" min="20000" max="400000" step="10000" required>
            <small>Amostra usada no ajuste</small>
          </label>
        </div>

        <label class="check" style="margin-top: 16px">
          <input v-model="form.window_features" type="checkbox">
          Usar janelas do passado (média, desvio e tendência das últimas 20 leituras) em vez do contador de ciclos
        </label>

        <div class="actions">
          <button class="btn" type="submit" :disabled="!canRun || sending || running">
            {{ running ? 'Aguarde o job atual' : 'Treinar modelo' }}
          </button>
          <span v-if="!canRun" class="small">Seu perfil possui acesso somente para visualização.</span>
          <span v-if="feedback" class="feedback">{{ feedback }}</span>
        </div>
      </form>
    </section>

    <section class="panel">
      <div class="panel-heading">
        <div>
          <h2>Histórico de treinos</h2>
          <p>Cada treino concluído gera uma nova versão (1.1.0, 1.2.0...).</p>
        </div>
      </div>
      <JobList :jobs="trainJobs" empty-text="Nenhum treino disparado pela interface ainda." />
    </section>
  </section>
</template>

<style src="../styles/pages.css"></style>
