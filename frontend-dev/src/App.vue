
<script setup lang="ts">
import { ref } from 'vue'

import LoginScreen from './components/LoginScreen.vue'
import Dashboard from './Dashboard.vue'
import Mensageria from './components/Mensageria.vue'
import AssistantChat from './components/AssistantChat.vue'
import InsightsPage from './components/InsightsPage.vue'
import LabPage from './components/LabPage.vue'
import TrainingPage from './components/TrainingPage.vue'
import DevicesPage from './components/DevicesPage.vue'

// ==========================================
// TIPOS
// ==========================================

type Role = 'admin' | 'operator' | 'viewer'

type Session = {
  token: string
  username: string
  role: Role
}

type Page =
  | 'dashboard'
  | 'insights'
  | 'laboratorio'
  | 'treinamento'
  | 'dispositivos'
  | 'mensageria'
  | 'assistente'

const PAGES: { id: Page; icon: string; label: string }[] = [
  { id: 'dashboard', icon: '📊', label: 'Dashboard' },
  { id: 'insights', icon: '🔎', label: 'Insights' },
  { id: 'laboratorio', icon: '🧪', label: 'Laboratório' },
  { id: 'treinamento', icon: '🧠', label: 'Treinamento' },
  { id: 'dispositivos', icon: '🏭', label: 'Dispositivos' },
  { id: 'mensageria', icon: '📨', label: 'Mensageria' },
  { id: 'assistente', icon: '💬', label: 'Assistente' }
]

// ==========================================
// AUTENTICACAO
// ==========================================

const session = ref<Session | null>(null)

const roleNames: Record<Role, string> = {
  admin: 'Administrador',
  operator: 'Operador',
  viewer: 'Visualizador'
}

// ==========================================
// NAVEGACAO
// ==========================================

const activePage = ref<Page>('dashboard')

function navigate(page: Page) {
  activePage.value = page
}

// ==========================================
// LOGIN E LOGOUT
// ==========================================

function handleAuthenticated(newSession: Session) {
  session.value = newSession
  activePage.value = 'dashboard'
}

function logout() {
  session.value = null
  activePage.value = 'dashboard'
}
</script>

<template>
  <!-- TELA DE LOGIN -->

  <LoginScreen
    v-if="!session"
    @authenticated="handleAuthenticated"
  />

  <!-- SISTEMA AUTENTICADO -->

  <template v-else>

    <!-- BARRA SUPERIOR -->

    <header class="session-bar">

      <div class="session-info">
        <span class="session-dot"></span>

        <div class="user-details">
          <strong>{{ session.username }}</strong>

          <span class="role-badge">
            {{ roleNames[session.role] }}
          </span>
        </div>
      </div>

      <button
        class="logout-button"
        type="button"
        @click="logout"
      >
        Sair da conta
      </button>

    </header>

    <!-- MENU DE NAVEGACAO -->

    <nav class="nav-bar" aria-label="Navegação principal">

      <div class="nav-inner">

        <button
          v-for="page in PAGES"
          :key="page.id"
          type="button"
          class="nav-button"
          :class="{ active: activePage === page.id }"
          @click="navigate(page.id)"
        >
          <span>{{ page.icon }}</span>
          {{ page.label }}
        </button>

      </div>

    </nav>

    <!-- PAGINAS -->

    <main>

      <Dashboard
        v-if="activePage === 'dashboard'"
        :session="session"
      />

      <Mensageria
        v-else-if="activePage === 'mensageria'"
        :token="session.token"
      />

      <AssistantChat
        v-else-if="activePage === 'assistente'"
        api-url="http://localhost:8001"
        :token="session.token"
      />

      <InsightsPage
        v-else-if="activePage === 'insights'"
        :token="session!.token"
        :role="session!.role"
      />

      <LabPage
        v-else-if="activePage === 'laboratorio'"
        :token="session!.token"
        :role="session!.role"
      />

      <TrainingPage
        v-else-if="activePage === 'treinamento'"
        :token="session!.token"
        :role="session!.role"
      />

      <DevicesPage
        v-else-if="activePage === 'dispositivos'"
        :token="session!.token"
        :role="session!.role"
      />

    </main>

  </template>
</template>

<style scoped>
.session-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px;
  padding: 14px 5%;
  background: #101b2c;
  border-bottom: 1px solid #26364c;
  font-family: Inter, Arial, sans-serif;
}

.session-info {
  display: flex;
  align-items: center;
  gap: 12px;
}

.session-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #34d399;
  box-shadow: 0 0 12px #34d39955;
}

.user-details {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  color: #e2e8f0;
  font-size: 14px;
}

.role-badge {
  background: #173349;
  color: #7dd3fc;
  padding: 6px 11px;
  border-radius: 20px;
  font-size: 11px;
  font-weight: 600;
}

.logout-button {
  background: transparent;
  border: 1px solid #475569;
  color: #e2e8f0;
  padding: 9px 16px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
}

.logout-button:hover {
  background: #253449;
}

/* ==========================================
   NAVEGACAO
   ========================================== */

.nav-bar {
  background: #0e192a;
  border-bottom: 1px solid #26364c;
  font-family: Inter, Arial, sans-serif;
}

.nav-inner {
  max-width: 1440px;
  margin: 0 auto;
  padding: 0 32px;
  display: flex;
  align-items: center;
  gap: 8px;
  /* 7 telas: rola na horizontal em telas estreitas */
  overflow-x: auto;
  scrollbar-width: thin;
}

.nav-button {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 17px 22px;
  border: none;
  border-bottom: 3px solid transparent;
  background: transparent;
  color: #94a3b8;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition:
    background 0.2s,
    color 0.2s,
    border-color 0.2s;
}

.nav-button:hover {
  color: #e2e8f0;
  background: #17263b;
}

.nav-button.active {
  color: #38bdf8;
  border-bottom-color: #38bdf8;
  background: #14243a;
}

.nav-button span {
  font-size: 17px;
}

main {
  min-height: calc(100vh - 130px);
  background: #0b1220;
}

@media (max-width: 600px) {
  .session-bar {
    padding: 12px 16px;
  }

  .nav-inner {
    padding: 0 12px;
    gap: 4px;
  }

  .nav-button {
    padding: 15px 12px;
    font-size: 13px;
  }
}
</style>
