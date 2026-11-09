
<script setup lang="ts">
import { ref } from 'vue'

type Role = 'admin' | 'operator' | 'viewer'

type Session = {
  token: string
  username: string
  role: Role
}

const emit = defineEmits<{
  (e: 'authenticated', session: Session): void
}>()

const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')

async function handleLogin() {
  if (loading.value) return

  loading.value = true
  error.value = ''

  try {
    const response = await fetch(
      'http://localhost:8001/api/auth/login',
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          username: username.value.trim(),
          password: password.value
        })
      }
    )

    if (response.status === 401) {
      error.value = 'Usuário ou senha incorretos.'
      return
    }

    if (!response.ok) {
      throw new Error('Erro na autenticação')
    }

    const data = await response.json()

    const validRoles = ['admin', 'operator', 'viewer']

    if (
      typeof data.access_token !== 'string' ||
      typeof data.username !== 'string' ||
      !validRoles.includes(data.role)
    ) {
      throw new Error('Resposta de login inválida')
    }

    password.value = ''

    emit('authenticated', {
      token: data.access_token,
      username: data.username,
      role: data.role as Role
    })

  } catch {
    error.value =
      'Não foi possível entrar. Verifique a conexão com a API.'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">

      <div class="brand">
        <div class="brand-icon">SF</div>
        <span>SMART FACTORY AIoT</span>
      </div>

      <h1>Bem-vindo de volta</h1>

      <p class="subtitle">
        Entre com suas credenciais para acessar
        o Centro de Controle Industrial.
      </p>

      <form @submit.prevent="handleLogin">

        <label for="username">Usuário</label>

        <input
          id="username"
          v-model="username"
          type="text"
          placeholder="Digite seu usuário"
          autocomplete="username"
          required
        />

        <label for="password">Senha</label>

        <input
          id="password"
          v-model="password"
          type="password"
          placeholder="Digite sua senha"
          autocomplete="current-password"
          required
        />

        <p v-if="error" class="error" role="alert">
          {{ error }}
        </p>

        <button
          type="submit"
          :disabled="loading"
        >
          {{ loading ? 'Autenticando...' : 'Entrar no sistema' }}
        </button>

      </form>

      <div class="footer">
        <span class="status-dot"></span>
        Acesso controlado por perfil de usuário
      </div>

    </div>

    <div class="bottom-text">
      Smart Factory AIoT · Sistema de Monitoramento Industrial
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  justify-content: center;
  align-items: center;
  flex-direction: column;
  padding: 24px;
  background:
    radial-gradient(
      ellipse at 50% 10%,
      #153353 0%,
      #0b1424 50%,
      #080e1b 100%
    );
  color: #e2e8f0;
  font-family: Inter, Arial, sans-serif;
}

.login-card {
  width: 100%;
  max-width: 440px;
  padding: 42px;
  background: #141f31;
  border: 1px solid #263b54;
  border-radius: 20px;
  box-shadow: 0 25px 80px #00000055;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  color: #38bdf8;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 2px;
  margin-bottom: 36px;
}

.brand-icon {
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  background: #173956;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 1px;
  color: #7dd3fc;
}

h1 {
  font-size: 30px;
  margin: 0 0 12px;
  color: white;
}

.subtitle {
  font-size: 14px;
  line-height: 1.7;
  color: #94a3b8;
  margin-bottom: 30px;
}

form {
  display: flex;
  flex-direction: column;
}

label {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 9px;
  color: #cbd5e1;
}

input {
  padding: 15px;
  margin-bottom: 22px;
  border-radius: 10px;
  border: 1px solid #33465e;
  background: #0c1525;
  color: white;
  font-size: 14px;
  outline: none;
  transition: border-color 0.2s;
}

input:focus {
  border-color: #38bdf8;
}

input::placeholder {
  color: #64748b;
}

button {
  width: 100%;
  padding: 15px;
  border: none;
  border-radius: 10px;
  background: #0891b2;
  color: white;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
  transition: background 0.2s;
}

button:hover:not(:disabled) {
  background: #0ea5c6;
}

button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.error {
  padding: 12px;
  color: #fda4af;
  background: #451b29;
  border-radius: 8px;
  font-size: 13px;
  margin: 0 0 16px;
}

.footer {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border-top: 1px solid #26364c;
  padding-top: 24px;
  margin-top: 30px;
  color: #94a3b8;
  font-size: 12px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #34d399;
}

.bottom-text {
  margin-top: 25px;
  color: #64748b;
  font-size: 12px;
  text-align: center;
}

@media (max-width: 480px) {
  .login-card {
    padding: 28px 22px;
  }

  h1 {
    font-size: 25px;
  }
}
</style>
