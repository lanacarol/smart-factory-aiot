
<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { Line } from 'vue-chartjs'
import Factory3D from './components/Factory3D.vue'

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

// ==========================================
// AUTENTICACAO E PERMISSOES
// ==========================================

type Role = 'admin' | 'operator' | 'viewer'

const props = defineProps<{
  session: {
    token: string
    username: string
    role: Role
  }
}>()

const canControl = computed(
  () =>
    props.session.role === 'admin' ||
    props.session.role === 'operator'
)

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Tooltip,
  Legend,
  Filler
)

// ==========================================
// TIPOS
// ==========================================

type DeviceEvent = {
  event_id?: string
  device_id: string
  timestamp: string
  type: 'telemetry' | 'state'
  payload: Record<string, number | boolean>
}

type PredictionEvent = {
  event_id?: string
  device_id: string
  timestamp: string
  type: 'prediction'
  payload: {
    rul_cycles: number
    health_percent: number
    maintenance_status: 'healthy' | 'warning' | 'critical'
    model_version: string
    cycle: number
  }
}

type HistoryPoint = {
  time: string
  motor: number
  vibration: number
  environment: number | null
}

// ==========================================
// CONEXOES - AMBIENTE DE DESENVOLVIMENTO
// ==========================================

const API_URL = 'http://localhost:8001'
const WS_URL = 'ws://localhost:8001/ws/factory'

// ==========================================
// ESTADO
// ==========================================

const devices = ref<Record<string, DeviceEvent>>({})
const predictions = ref<Record<string, PredictionEvent>>({})

const connected = ref(false)
const commandLoading = ref(false)
const feedback = ref('')
const now = ref(Date.now())

const history = ref<HistoryPoint[]>([])

// Historico do InfluxDB: 'live' mostra as ultimas 30 leituras
// recebidas pelo WebSocket; os demais periodos vem do banco.
type HistoryPeriod = 'live' | '15m' | '1h' | '6h' | '24h'

const HISTORY_PERIODS: { id: HistoryPeriod; label: string }[] = [
  { id: 'live', label: 'Ao vivo' },
  { id: '15m', label: '15 min' },
  { id: '1h', label: '1 h' },
  { id: '6h', label: '6 h' },
  { id: '24h', label: '24 h' }
]

const historyPeriod = ref<HistoryPeriod>('live')
const influxHistory = ref<HistoryPoint[]>([])
const historyLoading = ref(false)
const historyError = ref('')

const chartPoints = computed(() =>
  historyPeriod.value === 'live'
    ? history.value
    : influxHistory.value
)

let socket: WebSocket | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | undefined
let clockTimer: ReturnType<typeof setInterval> | undefined
let active = true

// ==========================================
// DISPOSITIVOS
// ==========================================

const motor = computed(
  () => devices.value['motor-01']?.payload
)

const environment = computed(
  () => devices.value['environment-01']?.payload
)

const conveyor = computed(
  () => devices.value['conveyor-01']?.payload.running === true
)

const fan = computed(
  () => devices.value['fan-01']?.payload.running === true
)

const motorRunning = computed(
  () => motor.value?.running === true
)

// Falha injetada pela interface (desgaste acelerado).
const faultActive = computed(
  () => motor.value?.fault_active === true
)

const motorCommandLoading = ref(false)
const motorFeedback = ref('')

// ==========================================
// ATUALIZACOES E CONEXAO
// ==========================================

function isRecent(timestamp?: string): boolean {
  if (!connected.value || !timestamp) {
    return false
  }

  const time = new Date(timestamp).getTime()

  return (
    Number.isFinite(time) &&
    now.value - time < 12000 &&
    now.value - time > -5000
  )
}

const lastUpdate = computed(() => {
  const timestamps = Object.values(devices.value)
    .map(device => new Date(device.timestamp).getTime())
    .filter(Number.isFinite)

  return timestamps.length
    ? Math.max(...timestamps)
    : 0
})

const online = computed(
  () =>
    connected.value &&
    lastUpdate.value > 0 &&
    now.value - lastUpdate.value < 12000
)

const motorOnline = computed(
  () => isRecent(devices.value['motor-01']?.timestamp)
)

const conveyorOnline = computed(
  () => isRecent(devices.value['conveyor-01']?.timestamp)
)

const fanOnline = computed(
  () => isRecent(devices.value['fan-01']?.timestamp)
)

const lastUpdateText = computed(() => {
  if (!lastUpdate.value) {
    return 'Aguardando dados...'
  }

  return new Date(lastUpdate.value)
    .toLocaleTimeString('pt-BR')
})

// ==========================================
// VALORES DOS SENSORES
// ==========================================

const temperature = computed(
  () => Number(motor.value?.temperature_c ?? 0)
)

const vibration = computed(
  () => Number(motor.value?.vibration_mm_s ?? 0)
)

const current = computed(
  () => Number(motor.value?.current_a ?? 0)
)

const ambient = computed(
  () => Number(environment.value?.temperature_c ?? 0)
)

const humidity = computed(
  () => Number(environment.value?.humidity_percent ?? 0)
)

// ==========================================
// MANUTENCAO PREDITIVA
// ==========================================

const prediction = computed(
  () => predictions.value['motor-01']
)

const predictionOnline = computed(
  () => isRecent(prediction.value?.timestamp)
)

const health = computed(
  () => Number(prediction.value?.payload.health_percent ?? 0)
)

const rul = computed(
  () => Number(prediction.value?.payload.rul_cycles ?? 0)
)

const cycle = computed(
  () => Number(prediction.value?.payload.cycle ?? 0)
)

const aiStatus = computed(() => {
  if (!predictionOnline.value) {
    return 'Sem previsão recente'
  }

  switch (prediction.value?.payload.maintenance_status) {
    case 'healthy':
      return 'Saudável'
    case 'warning':
      return 'Atenção'
    case 'critical':
      return 'Crítico'
    default:
      return 'Indisponível'
  }
})

const aiStatusClass = computed(() => {
  if (!predictionOnline.value) return 'neutral'

  switch (prediction.value?.payload.maintenance_status) {
    case 'healthy':
      return 'success'
    case 'warning':
      return 'warning'
    case 'critical':
      return 'danger'
    default:
      return 'neutral'
  }
})

const healthColor = computed(() => {
  if (!predictionOnline.value) return '#64748b'
  if (health.value < 30) return '#fb7185'
  if (health.value < 60) return '#fbbf24'
  return '#34d399'
})

const healthBarStyle = computed(() => ({
  width: `${predictionOnline.value ? health.value : 0}%`,
  background: healthColor.value
}))

const predictionTime = computed(() => {
  if (!prediction.value?.timestamp) {
    return 'Aguardando...'
  }

  return new Date(prediction.value.timestamp)
    .toLocaleTimeString('pt-BR')
})

// ==========================================
// ESTADO VISUAL DO MOTOR
// ==========================================

const motorStatus = computed(() => {
  if (!motorOnline.value) return 'Sem dados'
  if (!motorRunning.value) return 'Desligado'
  if (temperature.value >= 85) return 'Temperatura crítica'
  if (temperature.value >= 70) return 'Temperatura elevada'
  return 'Operação normal'
})

const motorStatusClass = computed(() => {
  if (!motorOnline.value || !motorRunning.value) return 'neutral'
  if (temperature.value >= 85) return 'danger'
  if (temperature.value >= 70) return 'warning'
  return 'success'
})

// ==========================================
// GRAFICOS
// ==========================================

const temperatureChart = computed(() => ({
  labels: chartPoints.value.map(item => item.time),
  datasets: [
    {
      label: 'Motor (°C)',
      data: chartPoints.value.map(item => item.motor),
      borderColor: '#38bdf8',
      backgroundColor: 'rgba(56,189,248,0.12)',
      borderWidth: 2,
      pointRadius: 0,
      tension: 0.3,
      fill: true
    },
    {
      label: 'Ambiente (°C)',
      data: chartPoints.value.map(item => item.environment),
      borderColor: '#34d399',
      backgroundColor: 'rgba(52,211,153,0.05)',
      borderWidth: 2,
      pointRadius: 0,
      tension: 0.3,
      fill: false
    }
  ]
}))

const vibrationChart = computed(() => ({
  labels: chartPoints.value.map(item => item.time),
  datasets: [
    {
      label: 'Vibração (mm/s)',
      data: chartPoints.value.map(item => item.vibration),
      borderColor: '#f59e0b',
      backgroundColor: 'rgba(245,158,11,0.12)',
      borderWidth: 2,
      pointRadius: 0,
      tension: 0.3,
      fill: true
    }
  ]
}))

const chartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  animation: false as const,
  plugins: {
    legend: {
      display: true,
      labels: { color: '#cbd5e1' }
    }
  },
  scales: {
    x: {
      ticks: {
        color: '#94a3b8',
        maxTicksLimit: 6
      },
      grid: {
        color: 'rgba(148,163,184,0.08)'
      }
    },
    y: {
      ticks: { color: '#94a3b8' },
      grid: {
        color: 'rgba(148,163,184,0.1)'
      }
    }
  }
}

// ==========================================
// PROCESSAR EVENTOS
// ==========================================

function addDeviceEvent(event: DeviceEvent) {
  const previous = devices.value[event.device_id]

  if (previous && event.timestamp < previous.timestamp) {
    return
  }

  devices.value[event.device_id] = event

  if (
    event.device_id === 'motor-01' &&
    event.type === 'telemetry'
  ) {
    const payload = event.payload

    history.value.push({
      time: new Date(event.timestamp)
        .toLocaleTimeString('pt-BR'),
      motor: Number(payload.temperature_c ?? 0),
      vibration: Number(payload.vibration_mm_s ?? 0),
      environment: devices.value['environment-01']
        ? Number(
            devices.value['environment-01']
              .payload.temperature_c ?? 0
          )
        : null
    })

    if (history.value.length > 30) {
      history.value.shift()
    }
  }
}

function addPrediction(event: PredictionEvent) {
  const previous = predictions.value[event.device_id]

  if (previous && event.timestamp < previous.timestamp) {
    return
  }

  predictions.value[event.device_id] = event
}

// ==========================================
// WEBSOCKET AUTENTICADO
// ==========================================

function connectWebSocket() {
  if (!active) return

  // O token permite que a API identifique o usuário.
  socket = new WebSocket(
    `${WS_URL}?token=${encodeURIComponent(props.session.token)}`
  )

  socket.onopen = () => {
    connected.value = true
    feedback.value = ''
  }

  socket.onmessage = message => {
    try {
      const data = JSON.parse(message.data)

      if (data.type === 'snapshot') {
        devices.value = data.devices || {}
        predictions.value = data.predictions || {}
        return
      }

      if (!data.device_id || !data.payload) {
        return
      }

      if (data.type === 'prediction') {
        addPrediction(data as PredictionEvent)
      } else if (
        data.type === 'telemetry' ||
        data.type === 'state'
      ) {
        addDeviceEvent(data as DeviceEvent)
      }
    } catch (error) {
      console.error('Erro ao receber evento:', error)
    }
  }

  socket.onclose = () => {
    connected.value = false
    socket = null

    if (active) {
      reconnectTimer = setTimeout(
        connectWebSocket,
        3000
      )
    }
  }

  socket.onerror = () => {
    socket?.close()
  }
}

// ==========================================
// CONTROLE DA ESTEIRA COM PERMISSOES
// ==========================================

async function sendCommand(action: 'ON' | 'OFF') {
  if (!canControl.value) {
    feedback.value =
      'Seu perfil não tem permissão para controlar equipamentos.'
    return
  }

  if (
    commandLoading.value ||
    !conveyorOnline.value
  ) {
    return
  }

  commandLoading.value = true
  feedback.value = ''

  try {
    const response = await fetch(
      `${API_URL}/api/conveyor/command`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${props.session.token}`
        },
        body: JSON.stringify({ action })
      }
    )

    if (!response.ok) {
      if (response.status === 403) {
        throw new Error('Permissão insuficiente')
      }

      if (response.status === 401) {
        throw new Error('Sessão inválida ou expirada')
      }

      throw new Error(`Erro HTTP ${response.status}`)
    }

    feedback.value =
      `Comando ${action} enviado. ` +
      'Aguardando atualização da esteira.'

  } catch (error) {
    console.error(error)

    feedback.value =
      error instanceof Error
        ? error.message
        : 'Erro ao enviar comando.'
  } finally {
    commandLoading.value = false
  }
}

// ==========================================
// INJECAO DE FALHA E MANUTENCAO DO MOTOR
// ==========================================

async function sendMotorCommand(
  action: 'INJECT_FAULT' | 'MAINTENANCE'
) {
  if (!canControl.value || motorCommandLoading.value) {
    return
  }

  motorCommandLoading.value = true
  motorFeedback.value = ''

  try {
    const response = await fetch(
      `${API_URL}/api/motor/command`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${props.session.token}`
        },
        body: JSON.stringify({ action })
      }
    )

    if (!response.ok) {
      if (response.status === 403) {
        throw new Error('Permissão insuficiente')
      }

      if (response.status === 401) {
        throw new Error('Sessão inválida ou expirada')
      }

      throw new Error(`Erro HTTP ${response.status}`)
    }

    motorFeedback.value =
      action === 'INJECT_FAULT'
        ? 'Falha injetada. Acompanhe a saúde prevista pela IA cair.'
        : 'Manutenção registrada. O desgaste do motor foi zerado.'

  } catch (error) {
    console.error(error)

    motorFeedback.value =
      error instanceof Error
        ? error.message
        : 'Erro ao enviar comando.'
  } finally {
    motorCommandLoading.value = false
  }
}

// ==========================================
// HISTORICO (INFLUXDB)
// ==========================================

type InfluxPoint = Record<string, number | string | null> & { time: string }

async function fetchHistory(deviceId: string, period: string) {
  const response = await fetch(
    `${API_URL}/api/history?device_id=${deviceId}&period=${period}`,
    { headers: { Authorization: `Bearer ${props.session.token}` } }
  )

  if (!response.ok) {
    throw new Error(`Histórico indisponível (HTTP ${response.status})`)
  }

  const data = await response.json()
  return data.points as InfluxPoint[]
}

async function loadHistory(period: Exclude<HistoryPeriod, 'live'>) {
  const [motorPoints, envPoints] = await Promise.all([
    fetchHistory('motor-01', period),
    fetchHistory('environment-01', period)
  ])

  const envByTime = new Map(
    envPoints.map(point => [point.time, point.temperature_c as number | null])
  )

  const longPeriod = period === '6h' || period === '24h'

  return motorPoints.map(point => {
    const date = new Date(point.time)
    return {
      time: longPeriod
        ? date.toLocaleString('pt-BR', { hour: '2-digit', minute: '2-digit' })
        : date.toLocaleTimeString('pt-BR'),
      motor: Number(point.temperature_c ?? 0),
      vibration: Number(point.vibration_mm_s ?? 0),
      environment: envByTime.get(point.time) ?? null
    }
  })
}

async function selectHistoryPeriod(period: HistoryPeriod) {
  historyPeriod.value = period
  historyError.value = ''

  if (period === 'live') return

  historyLoading.value = true

  try {
    influxHistory.value = await loadHistory(period)
  } catch (error) {
    historyError.value = error instanceof Error ? error.message : 'Erro ao carregar histórico'
  } finally {
    historyLoading.value = false
  }
}

// Ao abrir a pagina, preenche o modo ao vivo com os ultimos
// 15 minutos do InfluxDB, em vez de comecar com o grafico vazio.
async function prefillLiveHistory() {
  try {
    const points = await loadHistory('15m')

    if (history.value.length < 30) {
      history.value = [...points.slice(-(30 - history.value.length)), ...history.value]
    }
  } catch {
    // Sem historico: o grafico enche com as leituras ao vivo.
  }
}

// ==========================================
// FORMATACAO
// ==========================================

function formatNumber(value: number, digits = 1) {
  return value.toFixed(digits).replace('.', ',')
}

function formatInteger(value: number) {
  return Math.round(value).toLocaleString('pt-BR')
}

// ==========================================
// CICLO DE VIDA
// ==========================================

onMounted(() => {
  active = true
  connectWebSocket()
  prefillLiveHistory()

  clockTimer = setInterval(() => {
    now.value = Date.now()
  }, 1000)
})

onUnmounted(() => {
  active = false
  clearTimeout(reconnectTimer)
  clearInterval(clockTimer)
  socket?.close()
})
</script>

<template>
  <div class="dashboard">

    <!-- CABECALHO -->

    <header class="header">
      <div>
        <div class="eyebrow">SMART FACTORY AIoT</div>
        <h1>Centro de Controle Industrial</h1>
        <p>
          Monitoramento inteligente e manutenção
          preditiva em tempo real
        </p>
      </div>

      <div class="connection" :class="{ active: online }">
        <span class="dot"></span>
        {{ online ? 'Sistema online' : 'Sem dados recentes' }}
      </div>
    </header>

    <main>

      <!-- VISAO GERAL -->

      <section class="section-heading">
        <h2>Visão geral da fábrica</h2>
        <span>MQTT · RabbitMQ · WebSocket</span>
      </section>

      <div class="metrics">

        <article class="metric">
          <div class="metric-label">Temperatura do motor</div>
          <div class="metric-value">
            {{ motorOnline ? formatNumber(temperature) : '—' }}
            <small>°C</small>
          </div>
          <span class="metric-foot">Motor 01</span>
        </article>

        <article class="metric">
          <div class="metric-label">Vibração do motor</div>
          <div class="metric-value">
            {{ motorOnline ? formatNumber(vibration, 2) : '—' }}
            <small>mm/s</small>
          </div>
          <span class="metric-foot">Sensor de vibração</span>
        </article>

        <article class="metric">
          <div class="metric-label">Corrente elétrica</div>
          <div class="metric-value">
            {{ motorOnline ? formatNumber(current, 2) : '—' }}
            <small>A</small>
          </div>
          <span class="metric-foot">Consumo do motor</span>
        </article>

        <article class="metric">
          <div class="metric-label">Temperatura ambiente</div>
          <div class="metric-value">
            {{ formatNumber(ambient) }}
            <small>°C</small>
          </div>
          <span class="metric-foot">
            Umidade: {{ formatNumber(humidity) }}%
          </span>
        </article>

      </div>

      <!-- MANUTENCAO PREDITIVA -->

      <section class="section-heading">
        <h2>Inteligência Artificial · Manutenção Preditiva</h2>
        <span>Previsões produzidas por modelos treinados</span>
      </section>

      <div class="ai-grid">

        <article class="panel ai-card">
          <div class="ai-label">
            <span>Saúde estimada do motor</span>
            <span
              class="motor-badge"
              :class="aiStatusClass"
            >
              {{ aiStatus }}
            </span>
          </div>

          <div class="ai-value" :style="{ color: healthColor }">
            {{
              predictionOnline
                ? formatNumber(health, 1) + '%'
                : '—'
            }}
          </div>

          <div class="health-track">
            <div
              class="health-fill"
              :style="healthBarStyle"
            ></div>
          </div>

          <p class="ai-description">
            Estimativa calculada pelo modelo de regressão
            com base nos sensores e ciclos do equipamento.
          </p>
        </article>

        <article class="panel ai-card">
          <div class="ai-label">
            <span>⏳ Vida útil restante (RUL)</span>
            <span class="ai-tag">Predição</span>
          </div>

          <div class="ai-value">
            {{
              predictionOnline
                ? formatInteger(rul)
                : '—'
            }}
            <small>ciclos</small>
          </div>

          <p class="ai-description">
            Quantidade estimada de ciclos até o fim
            da vida útil sintética do motor.
          </p>

          <div class="ai-detail">
            Ciclos registrados:
            <strong>
              {{ predictionOnline ? formatInteger(cycle) : '—' }}
            </strong>
          </div>
        </article>

        <article class="panel ai-card">
          <div class="ai-label">
            <span>Diagnóstico preditivo</span>
            <span class="ai-tag">Modelo v1.0.0</span>
          </div>

          <div
            class="ai-diagnosis"
            :class="aiStatusClass"
          >
            {{ aiStatus }}
          </div>

          <p class="ai-description">
            {{
              !predictionOnline
                ? 'Aguardando uma previsão atualizada da IA.'
                : aiStatusClass === 'success'
                  ? 'O modelo não identificou necessidade de manutenção pelos limites demonstrativos.'
                  : aiStatusClass === 'warning'
                    ? 'A previsão indica atenção. Recomenda-se avaliar o equipamento.'
                    : 'A previsão atingiu os limites críticos definidos para a simulação.'
            }}
          </p>

          <div class="ai-detail">
            Última previsão:
            <strong>{{ predictionTime }}</strong>
          </div>
        </article>

      </div>

      <p class="ai-disclaimer">
        Resultados experimentais de modelos treinados com
        dados sintéticos. Os limites de alerta não foram
        validados para uso industrial.
      </p>

      <!-- GRAFICOS -->

      <div class="content-grid">

        <section class="panel">
          <div class="panel-header">
            <h2>Temperatura</h2>
            <span>
              {{
                historyPeriod === 'live'
                  ? 'Últimas 30 leituras'
                  : `InfluxDB · médias por intervalo`
              }}
            </span>
          </div>
          <div class="history-periods" role="group" aria-label="Período do histórico">
            <button
              v-for="period in HISTORY_PERIODS"
              :key="period.id"
              type="button"
              :class="{ active: historyPeriod === period.id }"
              :disabled="historyLoading"
              @click="selectHistoryPeriod(period.id)"
            >
              {{ period.label }}
            </button>
          </div>
          <p v-if="historyError" class="history-error">{{ historyError }}</p>
          <div class="chart-area">
            <Line
              :data="temperatureChart"
              :options="chartOptions"
            />
          </div>
        </section>

        <section class="panel">
          <div class="panel-header">
            <h2>Vibração do motor</h2>
            <span>
              mm/s ·
              {{ HISTORY_PERIODS.find(item => item.id === historyPeriod)?.label }}
            </span>
          </div>
          <div class="chart-area">
            <Line
              :data="vibrationChart"
              :options="chartOptions"
            />
          </div>
        </section>

      </div>

      <!-- MONITORAMENTO DO MOTOR -->

      <section class="panel motor-panel">
        <div class="motor-panel-content">
          <div>
            <h2>Monitoramento do motor</h2>
            <p>
              Estado operacional baseado nos sensores simulados.
            </p>
          </div>
          <span
            class="motor-badge"
            :class="motorStatusClass"
          >
            {{ motorStatus }}
          </span>
        </div>

        <div class="motor-panel-footer">
          <span>Última leitura: {{ lastUpdateText }}</span>
          <span>Limites de temperatura ilustrativos</span>
        </div>
      </section>

      <!-- EQUIPAMENTOS -->

      <section class="section-heading">
        <h2>Equipamentos e atuadores</h2>
        <span>Estados recebidos do simulador</span>
      </section>

      <div class="devices-grid">

        <article class="panel device">
          <div class="device-top">
            <div class="device-icon">Atuador remoto</div>
            <span
              class="status"
              :class="conveyorOnline && conveyor ? 'on' : 'off'"
            >
              {{
                !conveyorOnline
                  ? 'Sem dados'
                  : conveyor
                    ? 'Ligada'
                    : 'Desligada'
              }}
            </span>
          </div>

          <h3>Esteira transportadora</h3>
          <p>Controle remoto via RabbitMQ e MQTT</p>

          <div class="buttons">
            <button
              class="btn-green"
              :disabled="commandLoading || !conveyorOnline || !canControl"
              @click="sendCommand('ON')"
            >
              Ligar
            </button>

            <button
              class="btn-red"
              :disabled="commandLoading || !conveyorOnline || !canControl"
              @click="sendCommand('OFF')"
            >
              Desligar
            </button>
          </div>

          <p v-if="!canControl" class="permission-note">
            Seu perfil possui acesso somente para visualização.
          </p>

          <p v-if="feedback" class="feedback">
            {{ feedback }}
          </p>
        </article>

        <article class="panel device">
          <div class="device-top">
            <div class="device-icon">Simulação</div>
            <span
              class="status"
              :class="motorOnline && !faultActive ? 'on' : 'off'"
            >
              {{
                !motorOnline
                  ? 'Sem dados'
                  : faultActive
                    ? 'Falha ativa'
                    : 'Normal'
              }}
            </span>
          </div>

          <h3>Teste de falha do motor</h3>
          <p>
            Simula um rolamento danificado: o motor passa
            a se desgastar muito mais rápido e a IA deve
            detectar a queda de saúde.
          </p>

          <div class="buttons">
            <button
              class="btn-red"
              :disabled="motorCommandLoading || !motorOnline || !canControl || faultActive"
              @click="sendMotorCommand('INJECT_FAULT')"
            >
              Injetar falha
            </button>

            <button
              class="btn-green"
              :disabled="motorCommandLoading || !motorOnline || !canControl"
              @click="sendMotorCommand('MAINTENANCE')"
            >
              Registrar manutenção
            </button>
          </div>

          <p v-if="!canControl" class="permission-note">
            Seu perfil possui acesso somente para visualização.
          </p>

          <p v-if="motorFeedback" class="feedback">
            {{ motorFeedback }}
          </p>
        </article>

        <article class="panel device">
          <div class="device-top">
            <div class="device-icon">Atuador automático</div>
            <span
              class="status"
              :class="fanOnline && fan ? 'on' : 'off'"
            >
              {{
                !fanOnline
                  ? 'Sem dados'
                  : fan
                    ? 'Ligado'
                    : 'Desligado'
              }}
            </span>
          </div>

          <h3>Ventilador industrial</h3>
          <p>
            Atuador controlado automaticamente
            pela temperatura ambiente.
          </p>

          <div class="rule">
            Liga acima de 35 °C · Desliga abaixo de 30 °C
          </div>
        </article>

      </div>

      <!-- GEMEO DIGITAL -->

      <section class="section-heading section-3d">
        <h2>Visualização industrial 3D</h2>
        <span>Gêmeo digital conectado ao WebSocket</span>
      </section>

      <Factory3D
        :conveyor-on="conveyorOnline && conveyor"
        :fan-on="fanOnline && fan"
        :motor-temperature="temperature"
        :vibration="vibration"
        :ambient-temperature="ambient"
        :humidity="humidity"
        :online="online"
        :ai-status="predictionOnline ? prediction?.payload.maintenance_status : undefined"
      />

      <footer>
        Smart Factory AIoT · Vue 3 · Three.js ·
        FastAPI · RabbitMQ · MQTT · InfluxDB · Scikit-learn
      </footer>

    </main>
  </div>
</template>

<style>
* {
  box-sizing: border-box;
}

body {
  margin: 0;
  background: #0b1220;
  color: #e2e8f0;
  font-family: Inter, Arial, sans-serif;
}

button {
  font: inherit;
}

.dashboard {
  max-width: 1440px;
  margin: 0 auto;
  padding: 32px;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
  margin-bottom: 44px;
}

.eyebrow {
  color: #38bdf8;
  font-size: 12px;
  letter-spacing: 3px;
  font-weight: 700;
  margin-bottom: 10px;
}

h1 {
  font-size: 30px;
  margin: 0 0 8px;
}

h2 {
  font-size: 18px;
  margin: 0;
}

h3 {
  font-size: 19px;
  margin: 0 0 8px;
}

.header p,
.device p,
.motor-panel p {
  color: #94a3b8;
  margin: 0;
}

.connection {
  background: #332318;
  color: #fbbf24;
  border-radius: 30px;
  padding: 11px 17px;
  white-space: nowrap;
  font-size: 13px;
}

.connection.active {
  background: #11352d;
  color: #6ee7b7;
}

.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
  margin-right: 6px;
}

.section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.section-heading span,
.panel-header span {
  color: #64748b;
  font-size: 12px;
}

.metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 32px;
}

.metric,
.panel {
  background: #141f31;
  border: 1px solid #26364c;
  border-radius: 16px;
  padding: 22px;
}

.metric-label {
  color: #94a3b8;
  font-size: 13px;
}

.metric-value {
  font-size: 35px;
  font-weight: 750;
  margin: 18px 0 12px;
  white-space: nowrap;
}

.metric-value small {
  color: #94a3b8;
  font-size: 17px;
}

.metric-foot {
  color: #64748b;
  font-size: 12px;
}

/* INTELIGENCIA ARTIFICIAL */

.ai-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 12px;
}

.ai-card {
  min-height: 230px;
}

.ai-label {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  color: #cbd5e1;
  font-size: 13px;
  font-weight: 600;
}

.ai-value {
  margin: 24px 0 14px;
  font-size: 37px;
  font-weight: 750;
  white-space: nowrap;
}

.ai-value small {
  color: #94a3b8;
  font-size: 15px;
  font-weight: 500;
}

.ai-tag {
  color: #7dd3fc;
  background: #173349;
  padding: 7px 10px;
  border-radius: 20px;
  font-size: 11px;
}

.ai-description {
  color: #94a3b8;
  font-size: 12px;
  line-height: 1.7;
}

.health-track {
  height: 10px;
  background: #334155;
  border-radius: 20px;
  overflow: hidden;
}

.health-fill {
  height: 100%;
  border-radius: 20px;
  transition: width 0.5s ease;
}

.ai-diagnosis {
  font-size: 28px;
  font-weight: 750;
  margin-top: 25px;
}

.ai-diagnosis.success {
  color: #34d399;
}

.ai-diagnosis.warning {
  color: #fbbf24;
}

.ai-diagnosis.danger {
  color: #fb7185;
}

.ai-diagnosis.neutral {
  color: #94a3b8;
}

.ai-detail {
  margin-top: 14px;
  color: #94a3b8;
  font-size: 12px;
}

.ai-detail strong {
  color: #e2e8f0;
}

.ai-disclaimer {
  color: #64748b;
  font-size: 11px;
  line-height: 1.6;
  margin: 0 0 32px;
}

/* GRAFICOS */

.content-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 32px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 20px;
}

.chart-area {
  height: 270px;
}

/* MOTOR */

.motor-panel {
  margin-bottom: 36px;
}

.motor-panel-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
}

.motor-panel-content h2 {
  margin-bottom: 8px;
}

.motor-panel-content p {
  font-size: 13px;
}

.motor-badge {
  display: inline-flex;
  align-items: center;
  padding: 9px 14px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.motor-badge.success {
  background: #123b31;
  color: #6ee7b7;
}

.motor-badge.warning {
  background: #42331d;
  color: #fbbf24;
}

.motor-badge.danger {
  background: #42272b;
  color: #fda4af;
}

.motor-badge.neutral {
  background: #334155;
  color: #cbd5e1;
}

.motor-panel-footer {
  display: flex;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 22px;
  color: #64748b;
  font-size: 12px;
}

/* EQUIPAMENTOS */

.devices-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 36px;
}

.device-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.device-icon {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  color: #64748b;
}

.status {
  font-size: 12px;
  padding: 7px 12px;
  border-radius: 30px;
}

.status.on {
  background: #123b31;
  color: #6ee7b7;
}

.status.off {
  background: #42272b;
  color: #fda4af;
}

.device p {
  font-size: 13px;
  line-height: 1.6;
}

.buttons {
  display: flex;
  gap: 12px;
  margin-top: 24px;
}

.buttons button {
  border: 0;
  border-radius: 9px;
  padding: 11px 25px;
  cursor: pointer;
  color: white;
  font-weight: 600;
}

.btn-green {
  background: #059669;
}

.btn-green:hover:not(:disabled) {
  background: #047857;
}

.btn-red {
  background: #dc2626;
}

.btn-red:hover:not(:disabled) {
  background: #b91c1c;
}

button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.rule {
  margin-top: 24px;
  border: 1px solid #34445c;
  border-radius: 9px;
  padding: 12px;
  color: #94a3b8;
  font-size: 12px;
}

.feedback {
  margin-top: 12px !important;
  color: #38bdf8 !important;
}

.permission-note {
  margin-top: 15px !important;
  color: #fbbf24 !important;
  font-size: 12px;
}

.section-3d {
  margin-top: 36px;
}

footer {
  text-align: center;
  color: #64748b;
  padding: 25px 0 10px;
  font-size: 12px;
}

@media (max-width: 1100px) {
  .ai-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 950px) {
  .metrics {
    grid-template-columns: repeat(2, 1fr);
  }

  .content-grid,
  .devices-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 600px) {
  .dashboard {
    padding: 16px;
  }

  .header,
  .section-heading {
    align-items: flex-start;
    flex-direction: column;
  }

  .metrics {
    gap: 10px;
  }

  .metric {
    padding: 15px;
  }

  .metric-value {
    font-size: 25px;
  }

  .motor-panel-content {
    align-items: flex-start;
    flex-direction: column;
  }
}

.history-periods {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: -6px 0 14px;
}

.history-periods button {
  background: #0b1220;
  color: #94a3b8;
  border: 1px solid #334155;
  border-radius: 20px;
  padding: 5px 12px;
  font-size: 12px;
  cursor: pointer;
}

.history-periods button.active {
  background: #0c4a6e;
  border-color: #0284c7;
  color: #e0f2fe;
}

.history-periods button:disabled {
  opacity: 0.6;
  cursor: wait;
}

.history-error {
  color: #fda4af;
  font-size: 12px;
  margin: 0 0 10px;
}
</style>
