// ============================================================
// SMART FACTORY AIoT - sobe tudo com um unico `npm run dev`
// ============================================================
// 1. Garante o .env (gera senhas aleatorias se nao existir).
// 2. Garante o Docker rodando (abre o Docker Desktop no Windows).
// 3. Garante o arquivo de senhas do Mosquitto, coerente com o .env.
// 4. Sobe todos os containers (docker-compose.yml + docker-compose.dev.yml).
// 5. Instala as dependencias do frontend-dev (se faltar) e roda o Vite
//    com recarga automatica.
// Ctrl+C encerra o Vite e para os containers (dados sao mantidos).
//
// Flags:
//   --no-frontend   so sobe os containers e sai
//   --keep          no Ctrl+C mantem os containers rodando
// Sem dependencias externas: apenas Node.js puro.

import { spawn, spawnSync } from 'node:child_process'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { randomBytes } from 'node:crypto'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const IS_WIN = process.platform === 'win32'
const ARGS = new Set(process.argv.slice(2))
const COMPOSE = ['compose', '-f', 'docker-compose.yml', '-f', 'docker-compose.dev.yml']

const c = {
  cyan: (s) => `\x1b[36m${s}\x1b[0m`,
  green: (s) => `\x1b[32m${s}\x1b[0m`,
  yellow: (s) => `\x1b[33m${s}\x1b[0m`,
  red: (s) => `\x1b[31m${s}\x1b[0m`,
  bold: (s) => `\x1b[1m${s}\x1b[0m`,
}
const step = (msg) => console.log(`\n${c.cyan('▶')} ${c.bold(msg)}`)
const ok = (msg) => console.log(`  ${c.green('✔')} ${msg}`)
const warn = (msg) => console.log(`  ${c.yellow('!')} ${msg}`)
const fail = (msg) => {
  console.error(`\n${c.red('✖')} ${msg}`)
  process.exit(1)
}

const run = (cmd, args, opts = {}) =>
  spawnSync(cmd, args, { cwd: ROOT, stdio: 'inherit', shell: false, ...opts })

const runQuiet = (cmd, args) =>
  spawnSync(cmd, args, { cwd: ROOT, encoding: 'utf8', shell: false })

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const secret = (len = 24) =>
  randomBytes(len * 2).toString('base64').replace(/[^a-zA-Z0-9]/g, '').slice(0, len)

// ------------------------------------------------------------
// 1. .env
// ------------------------------------------------------------
function parseEnv(text) {
  const env = {}
  for (const line of text.split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/)
    if (m) env[m[1]] = m[2].replace(/^["']|["']$/g, '')
  }
  return env
}

function ensureEnv() {
  step('Verificando .env')
  const envPath = resolve(ROOT, '.env')
  const examplePath = resolve(ROOT, '.env.example')

  if (!existsSync(envPath)) {
    if (!existsSync(examplePath)) fail('.env.example nao encontrado.')
    let text = readFileSync(examplePath, 'utf8')
    const gen = {
      POSTGRES_PASSWORD: secret(),
      RABBITMQ_DEFAULT_PASS: secret(),
      INFLUXDB_PASSWORD: secret(),
      INFLUXDB_TOKEN: secret(48),
      MQTT_SIMULATOR_PASSWORD: secret(),
      MQTT_GATEWAY_PASSWORD: secret(),
    }
    for (const [k, v] of Object.entries(gen)) {
      text = text.replace(new RegExp(`^${k}=.*$`, 'm'), `${k}=${v}`)
    }
    writeFileSync(envPath, text)
    ok('.env criado a partir do .env.example com senhas aleatorias')
  }

  // Completa variaveis obrigatorias que possam faltar.
  let text = readFileSync(envPath, 'utf8')
  const env = parseEnv(text)
  const extras = []
  if (!env.JWT_SECRET_DEV) extras.push(`JWT_SECRET_DEV=${secret(48)}`)
  if (!env.OLLAMA_MODEL) extras.push('OLLAMA_MODEL=llama3.2:3b')
  if (extras.length) {
    text = text.replace(/\s*$/, '\n') + extras.join('\n') + '\n'
    writeFileSync(envPath, text)
    ok(`Variaveis adicionadas ao .env: ${extras.map((e) => e.split('=')[0]).join(', ')}`)
  }

  const finalEnv = parseEnv(readFileSync(envPath, 'utf8'))
  const required = [
    'POSTGRES_USER', 'POSTGRES_PASSWORD', 'POSTGRES_DB',
    'RABBITMQ_DEFAULT_USER', 'RABBITMQ_DEFAULT_PASS',
    'INFLUXDB_USERNAME', 'INFLUXDB_PASSWORD', 'INFLUXDB_ORG', 'INFLUXDB_BUCKET', 'INFLUXDB_TOKEN',
    'MQTT_SIMULATOR_PASSWORD', 'MQTT_GATEWAY_PASSWORD', 'JWT_SECRET_DEV',
  ]
  const missing = required.filter((k) => !finalEnv[k])
  if (missing.length) fail(`Variaveis vazias no .env: ${missing.join(', ')}`)
  ok('.env completo')
  return finalEnv
}

// ------------------------------------------------------------
// 2. Docker
// ------------------------------------------------------------
const dockerUp = () => runQuiet('docker', ['info', '--format', '{{.ServerVersion}}']).status === 0

async function ensureDocker() {
  step('Verificando Docker')
  if (runQuiet('docker', ['--version']).error) {
    fail('Docker nao encontrado. Instale o Docker Desktop: https://www.docker.com/products/docker-desktop')
  }
  if (dockerUp()) return ok('Docker rodando')

  if (IS_WIN) {
    const exe = 'C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe'
    if (existsSync(exe)) {
      warn('Docker parado. Abrindo o Docker Desktop...')
      spawn(exe, [], { detached: true, stdio: 'ignore' }).unref()
    }
  } else if (process.platform === 'darwin') {
    warn('Docker parado. Abrindo o Docker Desktop...')
    spawn('open', ['-a', 'Docker'], { detached: true, stdio: 'ignore' }).unref()
  }

  const limit = Date.now() + 180_000
  process.stdout.write('  aguardando o Docker ')
  while (Date.now() < limit) {
    if (dockerUp()) {
      process.stdout.write('\n')
      return ok('Docker rodando')
    }
    process.stdout.write('.')
    await sleep(3000)
  }
  process.stdout.write('\n')
  fail('O Docker nao respondeu em 3 minutos. Abra o Docker Desktop manualmente e rode de novo.')
}

// ------------------------------------------------------------
// 3. Senhas do Mosquitto
// ------------------------------------------------------------
function ensureMosquittoPasswords(env) {
  step('Verificando autenticacao do Mosquitto')
  const pwFile = resolve(ROOT, 'infra', 'mosquitto', 'passwords')
  if (existsSync(pwFile)) return ok('infra/mosquitto/passwords existe')

  const cfg = resolve(ROOT, 'infra', 'mosquitto')
  const r = run('docker', [
    'run', '--rm',
    '-v', `${cfg}:/cfg`,
    '-e', `SIM=${env.MQTT_SIMULATOR_PASSWORD}`,
    '-e', `GW=${env.MQTT_GATEWAY_PASSWORD}`,
    'eclipse-mosquitto:2', 'sh', '-c',
    'mosquitto_passwd -b -c /cfg/passwords simulator "$SIM" && ' +
      'mosquitto_passwd -b /cfg/passwords gateway "$GW" && chmod 0700 /cfg/passwords',
  ])
  if (r.status !== 0) fail('Nao foi possivel gerar infra/mosquitto/passwords.')
  ok('infra/mosquitto/passwords gerado a partir do .env')
}

// ------------------------------------------------------------
// 4. Containers
// ------------------------------------------------------------
function composeUp() {
  step('Subindo containers (pode demorar na primeira vez)')
  const r = run('docker', [...COMPOSE, 'up', '-d', '--build', '--remove-orphans'])
  if (r.status !== 0) fail('docker compose up falhou. Veja as mensagens acima.')
  ok('Containers no ar')
}

// ------------------------------------------------------------
// 5. Frontend (Vite)
// ------------------------------------------------------------
function ensureFrontendDeps() {
  step('Verificando dependencias do frontend-dev')
  const dir = resolve(ROOT, 'frontend-dev')
  if (existsSync(resolve(dir, 'node_modules', '.bin', IS_WIN ? 'vite.cmd' : 'vite'))) {
    return ok('node_modules ok')
  }
  const r = spawnSync('npm install', { cwd: dir, stdio: 'inherit', shell: true })
  if (r.status !== 0) fail('npm install do frontend-dev falhou.')
  ok('Dependencias instaladas')
}

function banner(withVite) {
  const line = '─'.repeat(58)
  console.log(`\n${c.green(line)}`)
  console.log(c.bold('  Smart Factory AIoT no ar!'))
  console.log(c.green(line))
  if (withVite) console.log(`  Frontend (dev, hot reload)  ${c.cyan('http://localhost:5173')}`)
  console.log(`  Frontend (container)        ${c.cyan('http://localhost:8080')}`)
  console.log(`  API dev / Swagger           ${c.cyan('http://localhost:8001/docs')}`)
  console.log(`  API / Swagger               ${c.cyan('http://localhost:8000/docs')}`)
  console.log(`  RabbitMQ Management         ${c.cyan('http://localhost:15672')}`)
  console.log(`  InfluxDB                    ${c.cyan('http://localhost:8086')}`)
  console.log(c.green(line))
  console.log('  npm run logs   -> logs dos containers')
  console.log('  npm run ps     -> estado dos containers')
  console.log('  npm run down   -> remove os containers')
  if (withVite) console.log(`  ${c.yellow('Ctrl+C')}         -> encerra o Vite e para os containers`)
  console.log(`${c.green(line)}\n`)
}

function startVite() {
  const dir = resolve(ROOT, 'frontend-dev')
  // Comando em string unica: no Windows o npm e um .cmd e exige shell.
  const vite = spawn('npm run dev -- --port 5173 --strictPort', {
    cwd: dir,
    stdio: 'inherit',
    shell: true,
  })

  let stopping = false
  const shutdown = () => {
    if (stopping) return
    stopping = true
    console.log(`\n${c.yellow('■')} Encerrando...`)
    if (!vite.killed) {
      if (IS_WIN) spawnSync('taskkill', ['/pid', String(vite.pid), '/T', '/F'], { stdio: 'ignore' })
      else vite.kill('SIGINT')
    }
    if (!ARGS.has('--keep')) {
      console.log('  parando containers (os dados sao mantidos)...')
      run('docker', [...COMPOSE, 'stop'])
    }
    process.exit(0)
  }
  process.on('SIGINT', shutdown)
  process.on('SIGTERM', shutdown)
  vite.on('exit', (code) => {
    if (!stopping) {
      warn(`Vite encerrou (codigo ${code}). Containers continuam rodando; use "npm run stop" para parar.`)
      process.exit(code ?? 0)
    }
  })
}

// ------------------------------------------------------------
async function main() {
  console.log(c.bold('\n=== SMART FACTORY AIoT - npm run dev ==='))
  const env = ensureEnv()
  await ensureDocker()
  ensureMosquittoPasswords(env)
  composeUp()

  if (ARGS.has('--no-frontend')) {
    banner(false)
    return
  }
  ensureFrontendDeps()
  banner(true)
  startVite()
}

main().catch((e) => fail(e?.stack || String(e)))

