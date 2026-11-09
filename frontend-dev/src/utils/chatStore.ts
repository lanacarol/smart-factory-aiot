// Conversa do assistente guardada fora do componente:
// - continua existindo (e recebendo a resposta) ao trocar de aba;
// - fica salva no navegador (localStorage), separada por usuario,
//   e volta depois de recarregar a pagina.

import { effectScope, reactive, watch } from 'vue'

// Situacao da fabrica usada para responder (enviada pela API).
export type Scenario = {
  at: string
  health_percent?: number | null
  rul_cycles?: number | null
  maintenance_status?: 'healthy' | 'warning' | 'critical' | null
  model_version?: string | null
  fault_active?: boolean | null
  motor_temperature_c?: number | null
  vibration_mm_s?: number | null
  ambient_temperature_c?: number | null
  conveyor_on?: boolean | null
  fan_on?: boolean | null
  open_alerts?: number
}

export type ChatMessage = {
  role: 'user' | 'assistant'
  text: string
  error?: boolean
  // Hora de envio da pergunta / inicio da resposta.
  sentAt?: number
  // Cenario em que a resposta foi gerada.
  context?: Scenario
  // Resposta do assistente: inicio e duracao, para mostrar o tempo.
  startedAt?: number
  seconds?: number
  done?: boolean
}

export type Conversation = {
  messages: ChatMessage[]
  sending: boolean
}

const MAX_MESSAGES = 60
const conversations: Record<string, Conversation> = {}

function storageKey(username: string) {
  return `smart-factory:assistente:${username}`
}

function load(username: string): ChatMessage[] {
  try {
    const raw = localStorage.getItem(storageKey(username))
    const messages = raw ? (JSON.parse(raw) as ChatMessage[]) : []

    // Resposta que estava chegando quando a pagina foi recarregada.
    for (const message of messages) {
      if (message.role === 'assistant' && !message.done) {
        message.done = true
        message.error = !message.text
        message.text = message.text
          ? `${message.text}\n\n*(resposta interrompida)*`
          : 'Resposta interrompida ao recarregar a página.'
      }
    }

    return Array.isArray(messages) ? messages : []
  } catch {
    return []
  }
}

function save(username: string, messages: ChatMessage[]) {
  try {
    localStorage.setItem(
      storageKey(username),
      JSON.stringify(messages.slice(-MAX_MESSAGES))
    )
  } catch {
    // Navegador sem armazenamento: a conversa fica so na memoria.
  }
}

export function useConversation(username: string): Conversation {
  let conversation = conversations[username]

  if (!conversation) {
    conversation = reactive({
      messages: load(username),
      sending: false
    }) as Conversation

    conversations[username] = conversation

    // Escopo proprio (detached): se o watch fosse criado no escopo
    // do componente, o Vue o desligaria ao trocar de aba e a
    // resposta que chega depois nao seria salva.
    effectScope(true).run(() => {
      watch(
        () => conversation!.messages,
        messages => save(username, messages),
        { deep: true }
      )
    })
  }

  return conversation
}

export function clearConversation(username: string) {
  const conversation = conversations[username]

  if (conversation && !conversation.sending) {
    conversation.messages.splice(0)
  }
}
