<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onUnmounted } from 'vue'
import { renderSafeMarkdown } from '../utils/safeMarkdown'
import { useConversation, clearConversation, type ChatMessage, type Scenario } from '../utils/chatStore'

const props = defineProps<{
  apiUrl: string
  token: string
  username: string
}>()

const authHeader = () => ({ Authorization: `Bearer ${props.token}` })

type ModelStatus = {
  status: 'starting' | 'pulling' | 'loading' | 'ready' | 'error'
  model: string
  progress: number | null
  detail: string
}

const SUGGESTIONS = [
  'Como está a saúde do motor agora?',
  'Existe algum alerta aberto? O que devo fazer?',
  'Explique as métricas do último treino em palavras simples.',
  'Como os dados fluem pela arquitetura da fábrica?'
]

const modelStatus = ref<ModelStatus | null>(null)
const statusError = ref(false)
// Conversa compartilhada: sobrevive a troca de aba e ao recarregar.
const conversation = useConversation(props.username)
const messages = computed(() => conversation.messages)
const sending = computed(() => conversation.sending)
const question = ref('')
const list = ref<HTMLElement | null>(null)

// Relogio para mostrar ha quantos segundos o assistente esta pensando.
const now = ref(Date.now())

let statusTimer: ReturnType<typeof setTimeout> | undefined
let clockTimer: ReturnType<typeof setInterval> | undefined
let active = true

function elapsed(message: ChatMessage) {
  if (message.seconds != null) return message.seconds
  if (!message.startedAt) return 0
  return Math.max(0, Math.round((now.value - message.startedAt) / 1000))
}

function timeOf(value?: number | string) {
  if (!value) return ''
  return new Date(value).toLocaleTimeString('pt-BR')
}

const STATUS_LABEL: Record<string, string> = {
  healthy: 'Saudável',
  warning: 'Atenção',
  critical: 'Crítico'
}

function num(value: number | null | undefined, digits = 1) {
  return value == null ? '—' : value.toLocaleString('pt-BR', { maximumFractionDigits: digits })
}

function onOff(value: boolean | null | undefined, on: string, off: string) {
  return value == null ? '—' : value ? on : off
}

function scenarioItems(context: Scenario) {
  return [
    `Saúde ${num(context.health_percent)}%`,
    `RUL ${num(context.rul_cycles, 0)} ciclos`,
    `Falha injetada: ${onOff(context.fault_active, 'sim', 'não')}`,
    `Motor ${num(context.motor_temperature_c)} °C`,
    `Vibração ${num(context.vibration_mm_s, 2)} mm/s`,
    `Ambiente ${num(context.ambient_temperature_c)} °C`,
    `Esteira ${onOff(context.conveyor_on, 'ligada', 'desligada')}`,
    `Ventilador ${onOff(context.fan_on, 'ligado', 'desligado')}`,
    `Alertas abertos: ${context.open_alerts ?? 0}`,
    `Modelo ${context.model_version ?? '—'}`
  ]
}

function clearChat() {
  clearConversation(props.username)
}

const ready = computed(() => modelStatus.value?.status === 'ready')

const statusText = computed(() => {
  if (statusError.value) return 'API indisponível'
  const status = modelStatus.value
  if (!status) return 'Verificando o modelo...'
  if (status.status === 'ready') return `Modelo pronto · ${status.model}`
  if (status.status === 'pulling') {
    const pct = status.progress != null ? ` ${status.progress.toFixed(0)}%` : ''
    return `Baixando o modelo${pct} (só na primeira vez)`
  }
  if (status.status === 'loading') return 'Carregando o modelo na memória...'
  return 'Aguardando o Ollama iniciar...'
})

async function pollStatus() {
  try {
    const response = await fetch(`${props.apiUrl}/api/assistant/status`, {
      headers: authHeader()
    })
    if (!response.ok) throw new Error(String(response.status))
    modelStatus.value = await response.json()
    statusError.value = false
  } catch {
    statusError.value = true
  }

  if (active && !ready.value) {
    statusTimer = setTimeout(pollStatus, 3000)
  }
}

async function scrollToEnd() {
  await nextTick()
  list.value?.scrollTo({ top: list.value.scrollHeight })
}

async function send(text?: string) {
  const content = (text ?? question.value).trim()
  if (!content || conversation.sending || !ready.value) return

  question.value = ''
  conversation.sending = true
  conversation.messages.push({ role: 'user', text: content, sentAt: Date.now() })
  conversation.messages.push({
    role: 'assistant',
    text: '',
    startedAt: Date.now(),
    done: false
  })
  // Objeto reativo dentro da conversa compartilhada: a resposta
  // continua sendo escrita mesmo se o usuario trocar de aba.
  const answer = conversation.messages[conversation.messages.length - 1]!
  await scrollToEnd()

  try {
    const response = await fetch(`${props.apiUrl}/api/assistant/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader() },
      body: JSON.stringify({ question: content })
    })

    if (!response.ok || !response.body) {
      let detail = 'Não foi possível consultar o assistente.'
      try {
        const data = await response.json()
        if (typeof data.detail === 'string') detail = data.detail
      } catch { /* resposta sem JSON */ }

      if (response.status === 503) {
        modelStatus.value = null
        pollStatus()
      }

      answer.text = detail
      answer.error = true
      return
    }

    // Cenario da fabrica usado nesta resposta.
    try {
      const header = response.headers.get('X-Assistant-Context')
      if (header) answer.context = JSON.parse(header) as Scenario
    } catch { /* sem cenario */ }

    // Resposta em streaming, pedaço a pedaço.
    const reader = response.body.getReader()
    const decoder = new TextDecoder()

    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      answer.text += decoder.decode(value, { stream: true })
      await scrollToEnd()
    }
  } catch {
    if (answer.text) {
      answer.text += '\n\n*(conexão interrompida)*'
    } else {
      answer.text = 'Falha de conexão com a API.'
      answer.error = true
    }
  } finally {
    answer.done = true
    answer.seconds = Math.round((Date.now() - (answer.startedAt ?? Date.now())) / 1000)
    conversation.sending = false
  }
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    send()
  }
}

onMounted(() => {
  pollStatus()
  scrollToEnd()
  clockTimer = setInterval(() => {
    now.value = Date.now()
  }, 1000)
})

// Ao sair da aba a resposta NAO e cancelada: ela continua
// chegando na conversa compartilhada.
onUnmounted(() => {
  active = false
  clearTimeout(statusTimer)
  clearInterval(clockTimer)
})
</script>

<template>
  <section class="assistant-panel">
    <div class="assistant-header">
      <div>
        <h2>Assistente da fábrica</h2>
        <p>
          LLM local (Ollama) dentro do Docker Compose. Responde com base nas
          leituras, previsões da IA, alertas e métricas atuais — nada vai para a nuvem.
        </p>
      </div>

      <div class="model-status" :class="{ ready }">
        <span class="dot" :class="{ pulse: !ready }"></span>
        {{ statusText }}
      </div>
    </div>

    <div v-if="modelStatus?.status === 'pulling' && modelStatus.progress != null" class="progress">
      <div class="progress-bar" :style="{ width: `${modelStatus.progress}%` }"></div>
    </div>

    <div ref="list" class="messages">
      <div v-if="!messages.length" class="empty">
        <p>Pergunte sobre o estado atual, as previsões ou a arquitetura:</p>
        <div class="suggestions">
          <button
            v-for="item in SUGGESTIONS"
            :key="item"
            type="button"
            :disabled="!ready || sending"
            @click="send(item)"
          >
            {{ item }}
          </button>
        </div>
      </div>

      <div
        v-for="(message, index) in messages"
        :key="index"
        class="message"
        :class="[message.role, { error: message.error }]"
      >
        <div class="role">
          {{ message.role === 'user' ? 'Você' : 'Assistente' }}
          <span v-if="message.sentAt || message.startedAt" class="time">
            · {{ timeOf(message.sentAt ?? message.startedAt) }}
          </span>
        </div>

        <div v-if="message.role === 'user'" class="text">{{ message.text }}</div>

        <!-- Saída do LLM: HTML sempre escapado em renderSafeMarkdown -->
        <div
          v-else-if="message.text"
          class="text markdown"
          v-html="renderSafeMarkdown(message.text)"
        ></div>

        <div v-else class="text thinking">
          Pensando... {{ elapsed(message) }} s
          <span class="hint">(o modelo roda na CPU; pode levar cerca de 1 minuto)</span>
        </div>

        <div
          v-if="message.role === 'assistant' && message.text"
          class="meta"
        >
          {{ message.done ? `respondido em ${elapsed(message)} s` : `escrevendo... ${elapsed(message)} s` }}
        </div>

        <div v-if="message.context" class="scenario">
          <div class="scenario-title">
            Cenário usado na resposta ({{ timeOf(message.context.at) }})
            <span
              v-if="message.context.maintenance_status"
              class="scenario-status"
              :class="message.context.maintenance_status"
            >
              {{ STATUS_LABEL[message.context.maintenance_status] }}
            </span>
          </div>
          <div class="scenario-items">
            <span v-for="item in scenarioItems(message.context)" :key="item">{{ item }}</span>
          </div>
        </div>
      </div>
    </div>

    <form class="composer" @submit.prevent="send()">
      <textarea
        v-model="question"
        rows="2"
        maxlength="500"
        :disabled="!ready"
        :placeholder="ready ? 'Digite sua pergunta (Enter envia, Shift+Enter quebra linha)' : 'Aguarde o modelo carregar...'"
        @keydown="onKeydown"
      ></textarea>

      <div class="composer-actions">
        <button type="submit" :disabled="!ready || sending || question.trim().length < 2">
          {{ sending ? 'Respondendo...' : 'Enviar' }}
        </button>
        <button
          type="button"
          class="clear"
          :disabled="sending || !messages.length"
          @click="clearChat"
        >
          Limpar conversa
        </button>
      </div>
    </form>
  </section>
</template>

<style scoped>
.assistant-panel {
  background: #111a2e;
  border: 1px solid #1e293b;
  border-radius: 18px;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 70vh;
}

.assistant-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.assistant-header p {
  color: #94a3b8;
  margin: 6px 0 0;
  font-size: 14px;
  max-width: 640px;
}

.model-status {
  background: #332318;
  color: #fbbf24;
  border-radius: 30px;
  padding: 9px 15px;
  font-size: 13px;
  white-space: nowrap;
}

.model-status.ready {
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

.dot.pulse {
  animation: pulse 1.2s ease-in-out infinite;
}

@keyframes pulse {
  50% { opacity: 0.3; }
}

.progress {
  height: 6px;
  background: #1e293b;
  border-radius: 6px;
  overflow: hidden;
}

.progress-bar {
  height: 100%;
  background: #38bdf8;
  transition: width 0.4s;
}

.messages {
  flex: 1;
  overflow-y: auto;
  max-height: 60vh;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-right: 4px;
}

.empty {
  color: #94a3b8;
}

.suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.suggestions button {
  background: #0b1220;
  color: #cbd5e1;
  border: 1px solid #334155;
  border-radius: 20px;
  padding: 8px 14px;
  cursor: pointer;
  font-size: 13px;
}

.suggestions button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.message {
  border-radius: 14px;
  padding: 12px 16px;
  max-width: 85%;
}

.message.user {
  align-self: flex-end;
  background: #1e3a5f;
}

.message.assistant {
  align-self: flex-start;
  background: #0b1220;
  border: 1px solid #1e293b;
}

.message.error {
  border-color: #7f1d1d;
  color: #fca5a5;
}

.role {
  font-size: 11px;
  letter-spacing: 1px;
  text-transform: uppercase;
  color: #64748b;
  margin-bottom: 4px;
}

.text {
  white-space: pre-wrap;
  line-height: 1.5;
  font-size: 14px;
}

.markdown {
  white-space: normal;
}

.markdown :deep(p) {
  margin: 0 0 8px;
}

.markdown :deep(ul),
.markdown :deep(ol) {
  margin: 0 0 8px;
  padding-left: 20px;
}

.markdown :deep(h4) {
  margin: 8px 0 6px;
  font-size: 15px;
}

.markdown :deep(code) {
  background: #1e293b;
  border-radius: 4px;
  padding: 1px 5px;
}

.markdown :deep(pre) {
  background: #1e293b;
  padding: 10px;
  border-radius: 8px;
  overflow-x: auto;
}

.thinking {
  color: #64748b;
  font-style: italic;
}

.composer {
  display: flex;
  gap: 10px;
}

.composer textarea {
  flex: 1;
  resize: none;
  background: #0b1220;
  color: #e2e8f0;
  border: 1px solid #334155;
  border-radius: 12px;
  padding: 10px 14px;
  font: inherit;
}

.composer button {
  background: #0284c7;
  color: white;
  border: none;
  border-radius: 12px;
  padding: 0 22px;
  cursor: pointer;
  font-weight: 600;
}

.composer button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@media (max-width: 720px) {
  .assistant-header {
    flex-direction: column;
  }

  .message {
    max-width: 100%;
  }
}

.thinking .hint {
  display: block;
  font-size: 12px;
  margin-top: 2px;
}

.meta {
  margin-top: 6px;
  font-size: 11px;
  color: #64748b;
}

.composer-actions {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.composer-actions button {
  flex: 1;
}

.composer .clear {
  background: transparent;
  color: #94a3b8;
  border: 1px solid #334155;
  font-weight: 500;
  font-size: 12px;
  padding: 6px 12px;
}

.role .time {
  text-transform: none;
  letter-spacing: 0;
}

.scenario {
  margin-top: 10px;
  padding: 10px 12px;
  border-radius: 10px;
  background: #111a2e;
  border: 1px dashed #26364c;
}

.scenario-title {
  font-size: 11px;
  color: #94a3b8;
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.scenario-status {
  padding: 2px 8px;
  border-radius: 12px;
  font-weight: 600;
}

.scenario-status.healthy { background: #11352d; color: #6ee7b7; }
.scenario-status.warning { background: #3b2a12; color: #fbbf24; }
.scenario-status.critical { background: #3f1d26; color: #fda4af; }

.scenario-items {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  font-size: 12px;
  color: #cbd5e1;
}
</style>
