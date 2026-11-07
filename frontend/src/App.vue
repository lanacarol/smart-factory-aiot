
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

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Tooltip,
  Legend,
  Filler
)

type DeviceEvent = {
  event_id?: string
  device_id: string
  timestamp: string
  type: 'telemetry' | 'state'
  payload: Record<string, number | boolean>
}

const API_URL = 'http://localhost:8000'
const WS_URL = 'ws://localhost:8000/ws/factory'

const devices = ref<Record<string, DeviceEvent>>({})
const connected = ref(false)
const commandLoading = ref(false)
const feedback = ref('')
const now = ref(Date.now())

const history = ref<{
  time: string
  motor: number
  vibration: number
  environment: number | null
}[]>([])

let socket: WebSocket | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | undefined
let clockTimer: ReturnType<typeof setInterval> | undefined
let active = true

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

const temperatureChart = computed(() => ({
  labels: history.value.map(item => item.time),
  datasets: [
    {
      label: 'Motor (°C)',
      data: history.value.map(item => item.motor),
      borderColor: '#38bdf8',
      backgroundColor: 'rgba(56, 189, 248, 0.10)',
      borderWidth: 2,
      pointRadius: 0,
      tension: 0.3,
      fill: true
    },
    {
      label: 'Ambiente (°C)',
      data: history.value.map(item => item.environment),
      borderColor: '#34d399',
      borderWidth: 2,
      pointRadius: 0,
      tension: 0.3,
      fill: false
    }
  ]
}))

const vibrationChart = computed(() => ({
  labels: history.value.map(item => item.time),
  datasets: [
    {
      label: 'Vibração (mm/s)',
      data: history.value.map(item => item.vibration),
      borderColor: '#f59e0b',
      backgroundColor: 'rgba(245, 158, 11, 0.12)',
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
      labels: {
        color: '#cbd5e1'
      }
    }
  },
  scales: {
    x: {
      ticks: {
        color: '#94a3b8',
        maxTicksLimit: 6
      },
      grid: {
        color: 'rgba(148, 163, 184, 0.08)'
      }
    },
    y: {
      ticks: {
        color: '#94a3b8'
      },
      grid: {
        color: 'rgba(148, 163, 184, 0.1)'
      }
    }
  }
}

function addEvent(event: DeviceEvent) {
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

    const newPoint = {
      time: new Date(event.timestamp)
        .toLocaleTimeString('pt-BR'),

      motor: Number(
        payload.temperature_c ?? 0
      ),

      vibration: Number(
        payload.vibration_mm_s ?? 0
      ),

      environment: devices.value['environment-01']
        ? Number(
            devices.value['environment-01']
              .payload.temperature_c ?? 0
          )
        : null
    }

    history.value.push(newPoint)

    if (history.value.length > 30) {
      history.value.shift()
    }
  }
}

function connectWebSocket() {
  if (!active) return

  socket = new WebSocket(WS_URL)

  socket.onopen = () => {
    connected.value = true
    feedback.value = ''
  }

  socket.onmessage = (message) => {
    try {
      const data = JSON.parse(message.data)

      if (data.type === 'snapshot') {
        devices.value = data.devices || {}
        return
      }

      if (data.device_id && data.payload) {
        addEvent(data as DeviceEvent)
      }
    } catch (error) {
      console.error('Evento inválido:', error)
    }
  }

  socket.onclose = () => {
    connected.value = false

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

async function sendCommand(action: 'ON' | 'OFF') {
  if (commandLoading.value || !online.value) {
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
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ action })
      }
    )

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`)
    }

    feedback.value =
      `Comando ${action} enviado. ` +
      'Aguardando atualização da esteira.'
  } catch (error) {
    console.error(error)

    feedback.value =
      'Erro ao enviar o comando. Confira a API.'
  } finally {
    commandLoading.value = false
  }
}

function formatNumber(
  value: number,
  digits = 1
) {
  return value
    .toFixed(digits)
    .replace('.', ',')
}

onMounted(() => {
  active = true

  connectWebSocket()

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

    <header class="header">
      <div>
        <div class="eyebrow">
          SMART FACTORY AIoT
        </div>

        <h1>Centro de Controle Industrial</h1>

        <p>
          Monitoramento inteligente de equipamentos
          em tempo real
        </p>
      </div>

      <div
        class="connection"
        :class="{ active: online }"
      >
        <span class="dot"></span>

        {{
          online
            ? 'Sistema online'
            : 'Sem dados recentes'
        }}
      </div>
    </header>

    <main>
      <section class="section-heading">
        <h2>Visão geral da fábrica</h2>

        <span>
          Dados recebidos via MQTT,
          RabbitMQ e WebSocket
        </span>
      </section>

      <div class="metrics">
        <article class="metric">
          <div class="metric-label">
            Temperatura do motor
          </div>

          <div class="metric-value">
            {{ formatNumber(temperature) }}
            <small>°C</small>
          </div>

          <span class="metric-foot">
            Motor 01
          </span>
        </article>

        <article class="metric">
          <div class="metric-label">
            Vibração do motor
          </div>

          <div class="metric-value">
            {{ formatNumber(vibration, 2) }}
            <small>mm/s</small>
          </div>

          <span class="metric-foot">
            Sensor de vibração
          </span>
        </article>

        <article class="metric">
          <div class="metric-label">
            Corrente elétrica
          </div>

          <div class="metric-value">
            {{ formatNumber(current, 2) }}
            <small>A</small>
          </div>

          <span class="metric-foot">
            Consumo do motor
          </span>
        </article>

        <article class="metric">
          <div class="metric-label">
            Temperatura ambiente
          </div>

          <div class="metric-value">
            {{ formatNumber(ambient) }}
            <small>°C</small>
          </div>

          <span class="metric-foot">
            Umidade:
            {{ formatNumber(humidity) }}%
          </span>
        </article>
      </div>

      <div class="content-grid">
        <section class="panel">
          <div class="panel-header">
            <h2>
              Temperatura em tempo real
            </h2>

            <span>
              Últimas 30 leituras
            </span>
          </div>

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

            <span>mm/s</span>
          </div>

          <div class="chart-area">
            <Line
              :data="vibrationChart"
              :options="chartOptions"
            />
          </div>
        </section>
      </div>

      <section class="section-heading">
        <h2>Equipamentos e atuadores</h2>

        <span>
          Estado recebido diretamente
          do simulador
        </span>
      </section>

      <div class="devices-grid">
        <article class="panel device">
          <div class="device-top">
            <div class="device-icon">
              ⚙️
            </div>

            <span
              class="status"
              :class="online && conveyor ? 'on' : 'off'"
            >
              {{
                online
                  ? conveyor
                    ? 'Ligada'
                    : 'Desligada'
                  : 'Sem dados'
              }}
            </span>
          </div>

          <h3>
            Esteira transportadora
          </h3>

          <p>
            Controle remoto via RabbitMQ e MQTT
          </p>

          <div class="buttons">
            <button
              class="btn-green"
              :disabled="commandLoading || !online"
              @click="sendCommand('ON')"
            >
              Ligar
            </button>

            <button
              class="btn-red"
              :disabled="commandLoading || !online"
              @click="sendCommand('OFF')"
            >
              Desligar
            </button>
          </div>

          <p
            v-if="feedback"
            class="feedback"
          >
            {{ feedback }}
          </p>
        </article>

        <article class="panel device">
          <div class="device-top">
            <div class="device-icon">
              💨
            </div>

            <span
              class="status"
              :class="online && fan ? 'on' : 'off'"
            >
              {{
                online
                  ? fan
                    ? 'Ligado'
                    : 'Desligado'
                  : 'Sem dados'
              }}
            </span>
          </div>

          <h3>
            Ventilador industrial
          </h3>

          <p>
            Atuador controlado automaticamente
            pela temperatura ambiente
          </p>

          <div class="rule">
            Liga acima de 35 °C ·
            Desliga abaixo de 30 °C
          </div>
        </article>
      </div>

      <footer>
        Smart Factory AIoT · Vue 3 · FastAPI ·
        RabbitMQ · MQTT · InfluxDB
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
.device p {
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

.content-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 36px;
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

.devices-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.device-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.device-icon {
  font-size: 30px;
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

.btn-red {
  background: #dc2626;
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

footer {
  text-align: center;
  color: #64748b;
  padding: 40px 0 10px;
  font-size: 12px;
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
}
</style>
