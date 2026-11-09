
<script setup lang="ts">
import {
  ref,
  computed,
  onMounted,
  onUnmounted
} from 'vue'

const props = defineProps<{
  token: string
}>()

type Queue = {
  name: string
  state: string
  messages: number
  messages_ready: number
  messages_unacknowledged: number
  consumers: number
}

const queues = ref<Queue[]>([])
const loading = ref(false)
const error = ref('')
const updatedAt = ref('')
const autoRefresh = ref(true)

let timer: ReturnType<typeof setInterval> | undefined
let active = true

const regularQueues = computed(() =>
  queues.value.filter(
    queue => queue.name !== 'q.dead-letter'
  )
)

const deadLetterQueue = computed(() =>
  queues.value.find(
    queue => queue.name === 'q.dead-letter'
  )
)

const totalConsumers = computed(() =>
  regularQueues.value.reduce(
    (sum, queue) => sum + queue.consumers,
    0
  )
)

const pendingMessages = computed(() =>
  regularQueues.value.reduce(
    (sum, queue) => sum + queue.messages,
    0
  )
)

async function loadQueues() {
  if (loading.value || !active) return

  loading.value = true

  try {
    const response = await fetch(
      'http://localhost:8001/api/messaging/queues',
      {
        headers: {
          Authorization: `Bearer ${props.token}`
        },
        cache: 'no-store'
      }
    )

    if (response.status === 401) {
      throw new Error(
        'Sua sessão expirou. Faça login novamente.'
      )
    }

    if (!response.ok) {
      throw new Error(
        `Não foi possível consultar o RabbitMQ: HTTP ${response.status}`
      )
    }

    const data = await response.json()

    if (!Array.isArray(data.queues)) {
      throw new Error('Resposta inválida da API.')
    }

    if (!active) return

    queues.value = data.queues
    updatedAt.value = new Date()
      .toLocaleTimeString('pt-BR')
    error.value = ''

  } catch (err) {
    if (!active) return

    error.value =
      err instanceof Error
        ? err.message
        : 'Erro desconhecido na consulta.'

  } finally {
    loading.value = false
  }
}

function formatNumber(value: number) {
  return value.toLocaleString('pt-BR')
}

onMounted(() => {
  active = true
  loadQueues()

  timer = setInterval(() => {
    if (autoRefresh.value) {
      loadQueues()
    }
  }, 5000)
})

onUnmounted(() => {
  active = false
  clearInterval(timer)
})
</script>

<template>
  <div class="messaging-page">

    <header class="page-header">
      <div>
        <span class="eyebrow">
          SMART FACTORY AIoT
        </span>

        <h1>Central de Mensageria</h1>

        <p>
          Monitoramento das filas e consumidores
          do RabbitMQ em tempo real.
        </p>
      </div>

      <div class="live-indicator">
        <span class="live-dot"></span>
        RabbitMQ Management
      </div>
    </header>

    <div class="metrics">

      <article class="metric-card">
        <span>Filas encontradas</span>
        <strong>{{ queues.length }}</strong>
        <small>Filas no broker</small>
      </article>

      <article class="metric-card">
        <span>Consumidores operacionais</span>
        <strong class="green">
          {{ totalConsumers }}
        </strong>
        <small>Conectados às filas</small>
      </article>

      <article class="metric-card">
        <span>Mensagens operacionais pendentes</span>
        <strong>
          {{ formatNumber(pendingMessages) }}
        </strong>
        <small>Excluindo a dead-letter</small>
      </article>

      <article class="metric-card">
        <span>Mensagens na dead-letter</span>
        <strong class="yellow">
          {{ formatNumber(
            deadLetterQueue?.messages ?? 0
          ) }}
        </strong>
        <small>Mensagens que exigem análise</small>
      </article>

    </div>

    <section class="panel">

      <div class="panel-heading">
        <div>
          <h2>Filas do RabbitMQ</h2>
          <p>
            Mensagens prontas, não confirmadas
            e consumidores conectados.
          </p>
        </div>

        <button
          class="refresh-button"
          type="button"
          :disabled="loading"
          @click="loadQueues"
        >
          {{ loading ? 'Atualizando...' : 'Atualizar agora' }}
        </button>
      </div>

      <div class="refresh-settings">
        <label>
          <input
            v-model="autoRefresh"
            type="checkbox"
          />
          Atualizar automaticamente a cada 5 segundos
        </label>

        <span>
          Última atualização:
          {{ updatedAt || 'Aguardando...' }}
        </span>
      </div>

      <p v-if="error" class="error" role="alert">
        {{ error }}
      </p>

      <div class="table-container">

        <table>
          <thead>
            <tr>
              <th>Fila</th>
              <th>Estado</th>
              <th>Prontas</th>
              <th>Não confirmadas</th>
              <th>Consumidores</th>
            </tr>
          </thead>

          <tbody>
            <tr
              v-for="queue in queues"
              :key="queue.name"
            >
              <td class="queue-name">
                {{ queue.name }}
              </td>

              <td>
                <span
                  class="status-badge"
                  :class="
                    queue.state === 'running'
                      ? 'running'
                      : 'stopped'
                  "
                >
                  {{ queue.state }}
                </span>
              </td>

              <td>
                {{ formatNumber(queue.messages_ready) }}
              </td>

              <td>
                {{
                  formatNumber(
                    queue.messages_unacknowledged
                  )
                }}
              </td>

              <td>
                <span
                  class="consumer-badge"
                  :class="{
                    offline: queue.consumers === 0
                  }"
                >
                  {{ queue.consumers }}
                </span>
              </td>
            </tr>

            <tr v-if="queues.length === 0">
              <td colspan="5" class="empty">
                Nenhuma fila carregada.
              </td>
            </tr>
          </tbody>
        </table>

      </div>
    </section>

    <section class="explanation-grid">

      <article class="info-panel">
        <h3>Como funciona a mensageria?</h3>

        <p>
          O RabbitMQ recebe mensagens dos produtores
          e as mantém em filas até que os consumidores
          responsáveis façam o processamento.
        </p>

        <p>
          Isso permite que os serviços trabalhem
          de maneira assíncrona.
        </p>
      </article>

      <article class="info-panel">
        <h3>O que acontece se um consumidor parar?</h3>

        <p>
          As mensagens que chegam à fila podem
          permanecer aguardando enquanto não há
          um consumidor disponível.
        </p>

        <p>
          Quando o consumidor volta, ele pode
          retomar o processamento das mensagens.
        </p>
      </article>

    </section>

    <section class="warning-panel">
      <h3>Fila de mensagens não processadas</h3>

      <p>
        A fila <strong>q.dead-letter</strong>
        contém mensagens encaminhadas para análise
        após falhas ou rejeições de processamento.
      </p>

      <p>
        Elas são exibidas separadamente das filas
        operacionais e não são apagadas por esta página.
      </p>
    </section>

  </div>
</template>

<style scoped>
.messaging-page {
  max-width: 1440px;
  margin: 0 auto;
  padding: 34px;
  min-height: 100vh;
  color: #e2e8f0;
  background: #0b1220;
  font-family: Inter, Arial, sans-serif;
}

* {
  box-sizing: border-box;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 18px;
  margin-bottom: 36px;
}

.eyebrow {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 3px;
  color: #38bdf8;
}

h1 {
  font-size: 30px;
  margin: 12px 0;
}

.page-header p,
.panel-heading p {
  color: #94a3b8;
  font-size: 14px;
  line-height: 1.6;
  margin: 0;
}

.live-indicator {
  display: flex;
  align-items: center;
  gap: 9px;
  border-radius: 25px;
  padding: 12px 16px;
  background: #11352d;
  color: #6ee7b7;
  font-size: 13px;
}

.live-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #34d399;
}

.metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 30px;
}

.metric-card {
  padding: 23px;
  border-radius: 16px;
  background: #141f31;
  border: 1px solid #26364c;
  display: flex;
  flex-direction: column;
  gap: 15px;
}

.metric-card span {
  color: #94a3b8;
  font-size: 13px;
}

.metric-card strong {
  font-size: 34px;
  color: #e2e8f0;
}

.metric-card .green {
  color: #34d399;
}

.metric-card .yellow {
  color: #fbbf24;
}

.metric-card small {
  font-size: 12px;
  color: #64748b;
}

.panel {
  background: #141f31;
  border: 1px solid #26364c;
  border-radius: 16px;
  padding: 24px;
  margin-bottom: 24px;
}

.panel-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
  flex-wrap: wrap;
}

h2 {
  font-size: 19px;
  margin: 0 0 8px;
}

.refresh-button {
  border: 1px solid #0e7490;
  background: #164e63;
  color: #e0f2fe;
  border-radius: 9px;
  padding: 11px 16px;
  cursor: pointer;
  font-weight: 600;
}

.refresh-button:hover:not(:disabled) {
  background: #155e75;
}

.refresh-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.refresh-settings {
  display: flex;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px;
  margin: 24px 0;
  color: #94a3b8;
  font-size: 12px;
}

.refresh-settings label {
  display: flex;
  gap: 8px;
  align-items: center;
}

.refresh-settings input {
  accent-color: #38bdf8;
}

.table-container {
  overflow-x: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
  min-width: 720px;
  text-align: left;
}

th {
  padding: 17px 12px;
  background: #0e192a;
  color: #94a3b8;
  font-size: 12px;
}

td {
  border-bottom: 1px solid #26364c;
  padding: 18px 12px;
  font-size: 13px;
}

.queue-name {
  color: #e2e8f0;
  font-weight: 600;
}

.status-badge {
  padding: 7px 12px;
  border-radius: 20px;
  font-size: 11px;
}

.status-badge.running {
  background: #123b31;
  color: #6ee7b7;
}

.status-badge.stopped {
  background: #42272b;
  color: #fda4af;
}

.consumer-badge {
  color: #6ee7b7;
  font-weight: 700;
}

.consumer-badge.offline {
  color: #fbbf24;
}

.empty {
  text-align: center;
  color: #94a3b8;
}

.explanation-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 18px;
  margin-bottom: 24px;
}

.info-panel,
.warning-panel {
  background: #141f31;
  border: 1px solid #26364c;
  border-radius: 14px;
  padding: 24px;
}

.info-panel h3,
.warning-panel h3 {
  font-size: 16px;
  margin: 0 0 13px;
}

.info-panel p,
.warning-panel p {
  color: #94a3b8;
  font-size: 13px;
  line-height: 1.7;
}

.warning-panel {
  border-color: #785a2c;
  background: #201e20;
}

.warning-panel h3 {
  color: #fbbf24;
}

.error {
  color: #fda4af;
  background: #42272b;
  padding: 13px;
  border-radius: 8px;
}

@media (max-width: 1000px) {
  .metrics {
    grid-template-columns: repeat(2, 1fr);
  }

  .explanation-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 600px) {
  .messaging-page {
    padding: 18px;
  }

  .metrics {
    grid-template-columns: 1fr;
  }
}
</style>
