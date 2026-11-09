<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onUnmounted } from 'vue'
import { renderSafeMarkdown } from '../utils/safeMarkdown'

const props = defineProps<{
  apiUrl: string
  token: string
}>()

const authHeader = () => ({ Authorization: `Bearer ${props.token}` })

type ModelStatus = {
  status: 'starting' | 'pulling' | 'loading' | 'ready' | 'error'
  model: string
  progress: number | null
  detail: string
}

type ChatMessage = {
  role: 'user' | 'assistant'
  text: string
  error?: boolean
}

const SUGGESTIONS = [
  'Como está a saúde do motor agora?',
  'Existe algum alerta aberto? O que devo fazer?',
  'Explique as métricas do último treino em palavras simples.',
  'Como os dados fluem pela arquitetura da fábrica?'
]

const modelStatus = ref<ModelStatus | null>(null)
const statusError = ref(false)
const messages = ref<ChatMessage[]>([])
const question = ref('')
const sending = ref(false)
const list = ref<HTMLElement | null>(null)

let statusTimer: ReturnType<typeof setTimeout> | undefined
let controller: AbortController | null = null
let active = true

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
  if (!content || sending.value || !ready.value) return

  question.value = ''
  sending.value = true
  messages.value.push({ role: 'user', text: content })
  messages.value.push({ role: 'assistant', text: '' })
  const answer = messages.value[messages.value.length - 1]!
  await scrollToEnd()

  controller = new AbortController()

  try {
    const response = await fetch(`${props.apiUrl}/api/assistant/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader() },
      body: JSON.stringify({ question: content }),
      signal: controller.signal
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

    // Resposta em streaming, pedaço a pedaço.
    const reader = response.body.getReader()
    const decoder = new TextDecoder()

    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      answer.text += decoder.decode(value, { stream: true })
      await scrollToEnd()
    }
  } catch (error) {
    if ((error as Error).name !== 'AbortError') {
      answer.text = 'Falha de conexão com a API.'
      answer.error = true
    }
  } finally {
    sending.value = false
    controller = null
  }
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    send()
  }
}

onMounted(pollStatus)

onUnmounted(() => {
  active = false
  clearTimeout(statusTimer)
  controller?.abort()
})
</script>

<template>
  <section class="assistant">
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
        <div class="role">{{ message.role === 'user' ? 'Você' : 'Assistente' }}</div>

        <div v-if="message.role === 'user'" class="text">{{ message.text }}</div>

        <!-- Saída do LLM: HTML sempre escapado em renderSafeMarkdown -->
        <div
          v-else-if="message.text"
          class="text markdown"
          v-html="renderSafeMarkdown(message.text)"
        ></div>

        <div v-else class="text thinking">Pensando...</div>
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

      <button type="submit" :disabled="!ready || sending || question.trim().length < 2">
        {{ sending ? 'Respondendo...' : 'Enviar' }}
      </button>
    </form>
  </section>
</template>

<style scoped>
.assistant {
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
</style>
