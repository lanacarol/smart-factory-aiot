<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { apiFetch, formatDateTime, type Role } from '../utils/api'

const props = defineProps<{
  token: string
  role: Role
}>()

type Device = {
  id: number
  device_id: string
  name: string
  device_type: string
  location: string | null
  active: boolean
  created_at: string
}

const TYPES: Record<string, string> = {
  motor: 'Motor',
  environment_sensor: 'Sensor ambiental',
  conveyor: 'Esteira',
  fan: 'Ventilador',
  sensor: 'Sensor',
  actuator: 'Atuador'
}

const isAdmin = computed(() => props.role === 'admin')

const devices = ref<Device[]>([])
const error = ref('')
const feedback = ref('')
const saving = ref(false)

const emptyForm = () => ({
  device_id: '',
  name: '',
  device_type: 'sensor',
  location: ''
})

const form = ref(emptyForm())

// Edicao em linha: copia do dispositivo sendo editado.
const editing = ref<string | null>(null)
const draft = ref({ name: '', device_type: 'sensor', location: '', active: true })

const activeCount = computed(() => devices.value.filter(device => device.active).length)

async function load() {
  try {
    const data = await apiFetch<{ devices: Device[] }>(props.token, '/api/devices')
    devices.value = data.devices
    error.value = ''
  } catch (err) {
    error.value = (err as Error).message
  }
}

async function create() {
  saving.value = true
  feedback.value = ''

  try {
    await apiFetch(props.token, '/api/devices', { method: 'POST', body: form.value })
    feedback.value = `Dispositivo ${form.value.device_id} cadastrado.`
    form.value = emptyForm()
    await load()
  } catch (err) {
    feedback.value = (err as Error).message
  } finally {
    saving.value = false
  }
}

function startEdit(device: Device) {
  editing.value = device.device_id
  draft.value = {
    name: device.name,
    device_type: device.device_type,
    location: device.location ?? '',
    active: device.active
  }
}

async function saveEdit(deviceId: string) {
  saving.value = true
  feedback.value = ''

  try {
    await apiFetch(props.token, `/api/devices/${encodeURIComponent(deviceId)}`, {
      method: 'PUT',
      body: draft.value
    })
    feedback.value = `Dispositivo ${deviceId} atualizado.`
    editing.value = null
    await load()
  } catch (err) {
    feedback.value = (err as Error).message
  } finally {
    saving.value = false
  }
}

async function remove(device: Device) {
  if (!window.confirm(`Excluir o dispositivo ${device.device_id}? Esta ação não pode ser desfeita.`)) {
    return
  }

  saving.value = true
  feedback.value = ''

  try {
    await apiFetch(props.token, `/api/devices/${encodeURIComponent(device.device_id)}`, {
      method: 'DELETE'
    })
    feedback.value = `Dispositivo ${device.device_id} excluído.`
    await load()
  } catch (err) {
    feedback.value = (err as Error).message
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="app-page">
    <header class="page-header">
      <div>
        <div class="eyebrow">PostgreSQL</div>
        <h1>Dispositivos</h1>
        <p>
          Cadastro de equipamentos da fábrica. Alterações são registradas na auditoria
          (<code>audit_logs</code>). Somente o perfil administrador pode editar.
        </p>
      </div>
      <span class="badge info">{{ activeCount }} de {{ devices.length }} ativos</span>
    </header>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="feedback" class="note" style="margin-bottom: 20px">{{ feedback }}</p>

    <section class="panel">
      <h2>Equipamentos cadastrados</h2>
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Nome</th>
              <th>Tipo</th>
              <th>Local</th>
              <th>Situação</th>
              <th>Cadastro</th>
              <th v-if="isAdmin"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="device in devices" :key="device.device_id">
              <template v-if="editing === device.device_id">
                <td><code>{{ device.device_id }}</code></td>
                <td><input v-model="draft.name" type="text" maxlength="100"></td>
                <td>
                  <select v-model="draft.device_type">
                    <option v-for="(label, value) in TYPES" :key="value" :value="value">{{ label }}</option>
                  </select>
                </td>
                <td><input v-model="draft.location" type="text" maxlength="100"></td>
                <td>
                  <label class="check">
                    <input v-model="draft.active" type="checkbox"> Ativo
                  </label>
                </td>
                <td class="small">{{ formatDateTime(device.created_at) }}</td>
                <td>
                  <div class="actions" style="margin: 0; flex-wrap: nowrap">
                    <button type="button" class="btn small" :disabled="saving" @click="saveEdit(device.device_id)">
                      Salvar
                    </button>
                    <button type="button" class="btn secondary small" @click="editing = null">Cancelar</button>
                  </div>
                </td>
              </template>

              <template v-else>
                <td><code>{{ device.device_id }}</code></td>
                <td>{{ device.name }}</td>
                <td>{{ TYPES[device.device_type] ?? device.device_type }}</td>
                <td>{{ device.location || '—' }}</td>
                <td>
                  <span class="badge" :class="device.active ? 'success' : ''">
                    {{ device.active ? 'Ativo' : 'Inativo' }}
                  </span>
                </td>
                <td class="small">{{ formatDateTime(device.created_at) }}</td>
                <td v-if="isAdmin">
                  <div class="actions" style="margin: 0; flex-wrap: nowrap">
                    <button type="button" class="btn secondary small" :disabled="saving" @click="startEdit(device)">
                      Editar
                    </button>
                    <button type="button" class="btn danger small" :disabled="saving" @click="remove(device)">
                      Excluir
                    </button>
                  </div>
                </td>
              </template>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="small" style="margin-top: 12px">
        Equipamentos com histórico (alertas ou comandos) não podem ser excluídos: desative-os.
      </p>
    </section>

    <section v-if="isAdmin" class="panel">
      <h2>Novo dispositivo</h2>
      <form @submit.prevent="create">
        <div class="form-grid">
          <label class="field">
            ID do dispositivo
            <input
              v-model.trim="form.device_id"
              type="text"
              required
              minlength="3"
              maxlength="50"
              pattern="[a-z0-9][a-z0-9\-]*"
              placeholder="ex.: sensor-02"
            >
            <small>Letras minúsculas, números e hífen</small>
          </label>
          <label class="field">
            Nome
            <input v-model.trim="form.name" type="text" required minlength="3" maxlength="100">
          </label>
          <label class="field">
            Tipo
            <select v-model="form.device_type">
              <option v-for="(label, value) in TYPES" :key="value" :value="value">{{ label }}</option>
            </select>
          </label>
          <label class="field">
            Local
            <input v-model.trim="form.location" type="text" required minlength="2" maxlength="100">
          </label>
        </div>
        <div class="actions">
          <button type="submit" class="btn" :disabled="saving">Cadastrar</button>
        </div>
      </form>
    </section>
  </section>
</template>

<style src="../styles/pages.css"></style>
