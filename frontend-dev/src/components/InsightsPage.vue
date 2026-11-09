<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { Line } from 'vue-chartjs'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Tooltip,
  Legend,
  Filler
} from 'chart.js'
import { apiFetch, formatDateTime, formatNumber, type Role } from '../utils/api'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend, Filler)

const props = defineProps<{
  token: string
  role: Role
}>()

type Status = 'healthy' | 'warning' | 'critical'

type HistoryItem = {
  timestamp: string
  health_percent: number
  rul_cycles: number
  maintenance_status: Status
  model_version: string
}

type Alert = {
  id: number
  severity: 'warning' | 'critical' | 'info'
  title: string
  description: string
  status: 'open' | 'acknowledged' | 'resolved'
  detected_at: string
  resolved_at: string | null
}

type Insights = {
  history: HistoryItem[]
  alerts: Alert[]
  alert_counts: { severity: string; status: string; total: number }[]
  commands: { action: string; status: string; requested_at: string }[]
}

const STATUS_INFO: Record<Status, { label: string; cls: string; advice: string }> = {
  healthy: {
    label: 'Saudável',
    cls: 'success',
    advice: 'Operação normal. Manter a inspeção de rotina e acompanhar a tendência da vibração.'
  },
  warning: {
    label: 'Atenção',
    cls: 'warning',
    advice:
      'Desgaste acima do normal. Programar manutenção preventiva: inspecionar rolamentos, ' +
      'verificar lubrificação e alinhamento, e reduzir a carga se possível.'
  },
  critical: {
    label: 'Crítico',
    cls: 'danger',
    advice:
      'Risco de falha em breve. Parar o motor na próxima janela possível, trocar rolamentos ' +
      'e verificar a parte elétrica antes de voltar a operar.'
  }
}

const canControl = computed(() => props.role === 'admin' || props.role === 'operator')

const data = ref<Insights | null>(null)
const error = ref('')
const feedback = ref('')
const sending = ref(false)
const faultActive = ref<boolean | null>(null)

let timer: ReturnType<typeof setTimeout> | undefined
let active = true

const history = computed(() => data.value?.history ?? [])
const latest = computed(() => history.value[history.value.length - 1])

const trend = computed(() => {
  // Variacao da saude no ultimo minuto (20 previsoes).
  const items = history.value
  if (items.length < 2) return null
  const old = items[Math.max(0, items.length - 21)]!
  return latest.value!.health_percent - old.health_percent
})

const openAlerts = computed(() =>
  (data.value?.alerts ?? []).filter(alert => alert.status !== 'resolved')
)

const totalAlerts = computed(() =>
  (data.value?.alert_counts ?? []).reduce((sum, item) => sum + Number(item.total), 0)
)

const chartData = computed(() => {
  const items = history.value.slice(-200)
  return {
    labels: items.map(item => new Date(item.timestamp).toLocaleTimeString('pt-BR')),
    datasets: [
      {
        label: 'Saúde (%)',
        data: items.map(item => item.health_percent),
        borderColor: '#34d399',
        backgroundColor: 'rgba(52, 211, 153, 0.12)',
        fill: true,
        pointRadius: 0,
        tension: 0.3,
        yAxisID: 'y'
      },
      {
        label: 'Vida útil restante (ciclos)',
        data: items.map(item => item.rul_cycles),
        borderColor: '#38bdf8',
        pointRadius: 0,
        tension: 0.3,
        yAxisID: 'y1'
      }
    ]
  }
})

const chartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  animation: false as const,
  interaction: { mode: 'index' as const, intersect: false },
  plugins: { legend: { labels: { color: '#cbd5e1' } } },
  scales: {
    x: { ticks: { color: '#64748b', maxTicksLimit: 8 }, grid: { color: '#1e293b' } },
    y: {
      min: 0,
      max: 100,
      position: 'left' as const,
      ticks: { color: '#34d399' },
      grid: { color: '#1e293b' }
    },
    y1: {
      min: 0,
      position: 'right' as const,
      ticks: { color: '#38bdf8' },
      grid: { display: false }
    }
  }
}

async function load() {
  try {
    data.value = await apiFetch<Insights>(props.token, '/api/insights?device_id=motor-01')

    // Estado da falha vem da ultima leitura do motor.
    const state = await apiFetch<{ devices?: Record<string, any> }>(props.token, '/api/factory/state')
    const motor = state.devices?.['motor-01']
    faultActive.value = motor ? motor.payload?.fault_active === true : null

    error.value = ''
  } catch (err) {
    error.value = (err as Error).message
  }

  if (active) timer = setTimeout(load, 3000)
}

async function motorCommand(action: 'INJECT_FAULT' | 'MAINTENANCE') {
  sending.value = true
  feedback.value = ''

  try {
    await apiFetch(props.token, '/api/motor/command', { method: 'POST', body: { action } })
    feedback.value = action === 'INJECT_FAULT'
      ? 'Falha injetada. Acompanhe a curva de saúde cair e os alertas abrirem.'
      : 'Manutenção registrada. O desgaste do motor foi zerado.'
  } catch (err) {
    feedback.value = (err as Error).message
  } finally {
    sending.value = false
  }
}

const ACTIONS: Record<string, string> = {
  INJECT_FAULT: 'Falha injetada',
  MAINTENANCE: 'Manutenção registrada'
}

onMounted(load)

onUnmounted(() => {
  active = false
  clearTimeout(timer)
})
</script>

<template>
  <section class="app-page">
    <header class="page-header">
      <div>
        <div class="eyebrow">Manutenção preditiva</div>
        <h1>Insights do motor</h1>
        <p>
          Previsões da IA em tempo real, histórico de saúde e alertas registrados no PostgreSQL
          (abertos só depois de 3 previsões seguidas, para evitar alarmes falsos).
        </p>
      </div>
      <span v-if="latest" class="badge" :class="STATUS_INFO[latest.maintenance_status].cls">
        {{ STATUS_INFO[latest.maintenance_status].label }}
      </span>
    </header>

    <p v-if="error" class="error">{{ error }}</p>

    <div class="metrics">
      <div class="metric-card">
        <span>Saúde prevista</span>
        <strong
          :class="!latest ? '' : latest.health_percent < 30 ? 'red' : latest.health_percent < 60 ? 'yellow' : 'green'"
        >
          {{ latest ? `${formatNumber(latest.health_percent, 1)}%` : '—' }}
        </strong>
        <small v-if="trend !== null">
          {{ trend >= 0 ? '▲' : '▼' }} {{ formatNumber(Math.abs(trend), 1) }} pontos no último minuto
        </small>
      </div>
      <div class="metric-card">
        <span>Vida útil restante</span>
        <strong>{{ latest ? Math.round(latest.rul_cycles).toLocaleString('pt-BR') : '—' }}</strong>
        <small>ciclos estimados</small>
      </div>
      <div class="metric-card">
        <span>Alertas abertos</span>
        <strong :class="openAlerts.length ? 'yellow' : 'green'">{{ openAlerts.length }}</strong>
        <small>{{ totalAlerts }} registrados no total</small>
      </div>
      <div class="metric-card">
        <span>Teste de falha</span>
        <strong :class="faultActive ? 'red' : 'green'" style="font-size: 20px">
          {{ faultActive === null ? 'Sem dados' : faultActive ? 'Falha ativa' : 'Normal' }}
        </strong>
        <small>Modelo {{ latest?.model_version ?? '—' }}</small>
      </div>
    </div>

    <section v-if="latest" class="panel">
      <div class="panel-heading">
        <div>
          <h2>Recomendação</h2>
          <p>{{ STATUS_INFO[latest.maintenance_status].advice }}</p>
        </div>
      </div>
      <div class="actions" style="margin-top: 0">
        <button
          type="button"
          class="btn danger"
          :disabled="!canControl || sending || faultActive === true"
          @click="motorCommand('INJECT_FAULT')"
        >
          Injetar falha
        </button>
        <button
          type="button"
          class="btn success"
          :disabled="!canControl || sending"
          @click="motorCommand('MAINTENANCE')"
        >
          Registrar manutenção
        </button>
        <span v-if="!canControl" class="small">Seu perfil possui acesso somente para visualização.</span>
        <span v-if="feedback" class="feedback">{{ feedback }}</span>
      </div>
    </section>

    <section class="panel">
      <h2>Saúde e vida útil ao longo do tempo</h2>
      <p class="muted">Últimas previsões recebidas pela API (uma a cada 3 s).</p>
      <div v-if="history.length" class="chart-box" style="height: 320px">
        <Line :data="chartData" :options="chartOptions" />
      </div>
      <p v-else class="note" style="margin-top: 14px">Aguardando previsões da IA...</p>
    </section>

    <div class="grid-2">
      <section class="panel">
        <h2>Alertas de manutenção</h2>
        <div class="table-container">
          <table v-if="data?.alerts.length">
            <thead>
              <tr>
                <th>Detectado</th>
                <th>Gravidade</th>
                <th>Descrição</th>
                <th>Situação</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="alert in data.alerts.slice(0, 12)" :key="alert.id">
                <td class="small">{{ formatDateTime(alert.detected_at) }}</td>
                <td>
                  <span class="badge" :class="alert.severity === 'critical' ? 'danger' : 'warning'">
                    {{ alert.severity === 'critical' ? 'Crítico' : 'Atenção' }}
                  </span>
                </td>
                <td>
                  <div>{{ alert.title }}</div>
                  <div class="small">{{ alert.description }}</div>
                </td>
                <td>
                  <span class="badge" :class="alert.status === 'resolved' ? '' : 'info'">
                    {{ alert.status === 'resolved' ? 'Resolvido' : 'Aberto' }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-else class="muted">Nenhum alerta registrado.</p>
        </div>
      </section>

      <section class="panel">
        <h2>Ações no motor</h2>
        <div class="table-container">
          <table v-if="data?.commands.length">
            <thead>
              <tr>
                <th>Quando</th>
                <th>Ação</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(command, index) in data.commands" :key="index">
                <td class="small">{{ formatDateTime(command.requested_at) }}</td>
                <td>{{ ACTIONS[command.action] ?? command.action }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="muted">Nenhuma ação registrada.</p>
        </div>
      </section>
    </div>
  </section>
</template>

<style src="../styles/pages.css"></style>
