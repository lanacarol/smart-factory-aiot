# Smart Factory AIoT

### Sistema Inteligente de Monitoramento Industrial e Manutenção Preditiva

Projeto acadêmico de uma fábrica inteligente que integra Internet das Coisas Industrial (IIoT), inteligência artificial, comunicação distribuída, bancos de dados e visualização tridimensional.

O sistema simula o funcionamento de equipamentos industriais, coleta dados em tempo real, estima a saúde e a vida útil restante de um motor e permite monitorar e controlar dispositivos por meio de um dashboard web.

## 1. Objetivo

Desenvolver uma solução de Smart Factory capaz de:

- Simular equipamentos e sensores industriais.
- Monitorar telemetrias em tempo real.
- Armazenar dados históricos e operacionais.
- Detectar condições de manutenção preventiva.
- Estimar a saúde e a vida útil restante de equipamentos.
- Controlar uma esteira transportadora remotamente.
- Visualizar a fábrica por meio de um gêmeo digital 3D.
- Registrar comandos e alertas em banco de dados.

## 2. Tecnologias utilizadas

| Camada | Tecnologias |
|---|---|
| Frontend | Vue 3, TypeScript, Vite |
| Visualização 3D | Three.js |
| Backend | Python, FastAPI |
| Comunicação IoT | MQTT, Eclipse Mosquitto |
| Mensageria | RabbitMQ |
| Banco de séries temporais | InfluxDB |
| Banco de dados relacional | PostgreSQL |
| Inteligência artificial | Python, Scikit-learn |
| LLM local | Ollama com `llama3.2:3b` (CPU) |
| Infraestrutura | Docker, Docker Compose |

## 3. Arquitetura do sistema

A solução utiliza serviços independentes para simular, transportar, armazenar e processar informações industriais.

### Fluxo de telemetria

1. O simulador gera leituras dos dispositivos.
2. As informações são publicadas via MQTT.
3. O gateway MQTT encaminha os eventos ao RabbitMQ.
4. O Influx Writer persiste as telemetrias no InfluxDB.
5. O serviço de IA processa os dados do motor.
6. A IA publica previsões de saúde e vida útil restante.
7. O FastAPI distribui eventos em tempo real pelo WebSocket.
8. O dashboard Vue exibe indicadores, gráficos e o gêmeo digital.

### Fluxo de comandos

1. O usuário liga ou desliga a esteira pelo dashboard.
2. O frontend solicita a ação ao FastAPI.
3. A API registra o comando no PostgreSQL.
4. O comando é encaminhado pelo RabbitMQ.
5. O gateway de comandos publica a ação via MQTT.
6. O simulador recebe a instrução e altera o estado da esteira.
7. O novo estado é transmitido ao dashboard.

### Fluxo de manutenção preditiva

1. A IA recebe os dados do motor.
2. O modelo estima a saúde do equipamento e os ciclos restantes.
3. A previsão é classificada como `healthy`, `warning` ou `critical`.
4. A previsão é publicada no RabbitMQ.
5. O FastAPI recebe o evento e atualiza os dados em tempo real.
6. Condições de atenção ou criticidade podem gerar alertas no PostgreSQL.
7. Previsões saudáveis podem resolver alertas ativos.

## 4. Equipamentos simulados

| Equipamento | Identificador | Função |
|---|---|---|
| Motor industrial | `motor-01` | Monitoramento de temperatura, vibração, corrente e desgaste |
| Sensor ambiental | `environment-01` | Monitoramento de temperatura ambiente e umidade |
| Esteira transportadora | `conveyor-01` | Controle de funcionamento ON/OFF |
| Ventilador industrial | `fan-01` | Resfriamento automático conforme a temperatura |

O simulador gera novas leituras aproximadamente a cada três segundos.

## 5. Inteligência artificial

A manutenção preditiva utiliza modelos de aprendizado de máquina treinados com dados sintéticos de operação industrial.

### Dataset

A base sintética é gerada pelo **Laboratório de Dados** (ou por `ai/generate_dataset.py`). O padrão são 1.000.000 de registros: 200 motores × 5.000 ciclos. Parâmetros configuráveis:

- percentual de motores que chegam à falha no período;
- modos de falha: geral, rolamento (vibração), superaquecimento (temperatura) e elétrica (corrente);
- ruído dos sensores, leituras faltantes e outliers;
- período simulado em dias, com ciclo dia/noite na temperatura ambiente;
- semente, para reproduzir a mesma base.

### Atributos (código único)

`ai/features.py` é usado **no treino e na inferência em tempo real**, então os dois calculam os atributos da mesma forma. Há dois conjuntos:

- **instant** (modelo 1.0.0): leituras do instante + contador de ciclos. O contador zera quando o simulador reinicia, e o modelo acabava "lendo o relógio" em vez dos sintomas.
- **window** (padrão desde a 1.1.0): leituras do instante + **janelas do passado** (média, desvio e tendência das últimas 20 leituras) de temperatura, vibração e corrente, sem o contador de ciclos.

### Modelos

Dois modelos `HistGradientBoostingRegressor`:

- **RUL**: vida útil restante do motor, em ciclos.
- **Health**: percentual de saúde do equipamento.

O treino roda pela tela **Treinamento** (ou `ai/train_models.py`). Cada treino gera uma nova versão (1.1.0, 1.2.0...) e a inferência passa a usar o modelo novo **sem reiniciar**, ao detectar a mudança em `ai/models/metadata.json`.

### Resultados obtidos (versão 1.2.0, atributos com janelas)

| Métrica (teste) | Modelo RUL | Modelo Health |
|---|---:|---:|
| MAE | 561,74 ciclos | 2,91 pontos percentuais |
| RMSE | 793,66 ciclos | 4,11 pontos percentuais |
| R² | 0,807 | 0,982 |
| MAE da base (prevê sempre a média) | 1.502,33 ciclos | 26,85 pontos percentuais |

As variáveis mais importantes passaram a ser a **média da vibração** e a **média da corrente**, ou seja, os sintomas do desgaste. A RUL ficou menos precisa que na versão 1.0.0 (R² 0,97), que usava o contador de ciclos: sem ele, a vida restante precisa ser inferida só pelos sintomas, o que é mais difícil, mas não depende mais do relógio do simulador.

Os dados foram separados por motores distintos nos conjuntos de treinamento, validação e teste, para avaliar a generalização a equipamentos não utilizados no treinamento.

**Limitação:** os resultados foram obtidos com dados sintéticos. Eles demonstram o funcionamento da abordagem proposta, mas não equivalem a uma validação em equipamentos industriais reais.

## 6. Dashboard e gêmeo digital

O frontend permite:

- Acompanhar informações industriais em tempo real.
- Visualizar gráficos de temperatura e vibração.
- Consultar a saúde estimada do motor.
- Acompanhar a vida útil restante (RUL).
- Ver a classificação de manutenção.
- Ligar e desligar a esteira.
- Observar os equipamentos em uma representação tridimensional.

O gêmeo digital foi desenvolvido com Three.js e representa visualmente o motor, a esteira e o ventilador.

### Injeção de falha (demonstração)

O cartão **Teste de falha do motor** no dashboard (perfis admin e operator) envia comandos ao motor pelo mesmo caminho da esteira: API → RabbitMQ → command-gateway → MQTT → simulador.

- **Injetar falha**: simula um rolamento danificado. O motor passa a se desgastar cerca de 60 ciclos a cada leitura, com mais vibração e temperatura. Em cerca de 80 s a IA passa para *Atenção* e em cerca de 150 s para *Crítico*; os alertas são abertos no PostgreSQL e o motor fica laranja/vermelho no gêmeo digital, tremendo conforme a vibração.
- **Registrar manutenção**: encerra a falha e zera o desgaste.

Bancos criados antes desta função precisam da migração `infra/postgres/migrations/001-motor-commands.sql`, que libera as novas ações na tabela `command_history`.

### Telas de IA e cadastro

- **Insights**: saúde e vida útil ao longo do tempo, alertas abertos e resolvidos, recomendação de manutenção e os botões de injeção de falha e manutenção.
- **Laboratório de Dados**: configura a base sintética e acompanha a geração (fila `q.jobs.generate`).
- **Treinamento**: modelo em uso, métricas comparadas à base, gráfico previsto × real, importância das variáveis e disparo de treino com progresso (fila `q.jobs.train`).
- **Dispositivos**: cadastro, edição, desativação e exclusão de equipamentos (perfil admin), com registro em `audit_logs`.
- **Dashboard**: os gráficos abrem com o histórico do InfluxDB e permitem ver 15 min, 1 h, 6 h ou 24 h.

Os jobs são executados pelo serviço `ai-jobs`, um por vez. O andamento volta pelo RabbitMQ (`job.status.*`) e fica na tabela `ai_jobs`.

Os alertas têm **histerese**: o status previsto precisa se repetir em 3 previsões seguidas para abrir, mudar ou resolver um alerta, evitando alarmes piscando por ruído.

### Assistente com LLM local

A aba **Assistente** é um chat que responde em linguagem natural sobre o estado atual da fábrica, as previsões da IA, os alertas abertos, as métricas do último treino e a arquitetura.

- O LLM (`llama3.2:3b`) roda no container `ollama`, em CPU, sem chave de API e sem enviar dados para a nuvem. O container não tem porta publicada: só a API conversa com ele.
- O LLM nunca acessa os bancos. A API monta um resumo pronto (leituras, previsões, alertas do PostgreSQL e `ai/models/metadata.json`) e envia junto da pergunta. Não há ferramentas (tool calling).
- Ao subir, a API baixa o modelo (só na primeira vez, cerca de 2 GB) e já o carrega na memória. A interface mostra "Baixando/Carregando o modelo" até ele ficar pronto.
- A resposta chega em streaming. A saída do LLM é tratada como texto não confiável: o Markdown é renderizado com todo HTML escapado e sem imagens ou links.
- Exige login (qualquer perfil). Limite de 6 perguntas por minuto por usuário (`ASSISTANT_RATE_LIMIT`), e cada pergunta é registrada em `audit_logs` com a ação `assistant_question`, o usuário e o perfil.
- No ambiente de desenvolvimento, a aba fica no `frontend-dev` (porta 5174) e usa a `api-dev` (porta 8001).

Recomenda-se pelo menos 8 GB de memória para o Docker/WSL2.

## 7. Banco de dados PostgreSQL

O sistema utiliza cinco tabelas principais:

| Tabela | Responsabilidade |
|---|---|
| `devices` | Cadastro dos equipamentos |
| `monitoring_rules` | Regras e limites de monitoramento |
| `maintenance_alerts` | Alertas de manutenção |
| `command_history` | Histórico dos comandos enviados |
| `audit_logs` | Estrutura para auditoria de operações |

Os arquivos de inicialização estão em:

- `infra/postgres/schema.sql`
- `infra/postgres/seed.sql`

Em uma instalação com volume de dados vazio, o PostgreSQL executa esses scripts automaticamente e cadastra os quatro equipamentos iniciais.

Os registros de telemetria são armazenados separadamente no InfluxDB.

## 8. Execução do projeto

### Pré-requisitos

- Docker Desktop.
- Docker Compose.
- Node.js e npm.
- Python, para geração de dados e treinamento local dos modelos.


### Configuração do ambiente

Clone o repositório:

```powershell
git clone https://github.com/lanacarol/smart-factory-aiot.git
cd smart-factory-aiot
```

Crie o arquivo `.env` a partir do exemplo:

```powershell
Copy-Item .env.example .env
```

Configure suas próprias credenciais no `.env`.

O arquivo `.env` contém informações sensíveis e não deve ser enviado ao GitHub.

**Atenção:** os usuários e as senhas do Mosquitto também precisam corresponder à configuração de autenticação em `infra/mosquitto`.

### Subir tudo com um único comando

Na raiz do projeto (só precisa de Docker Desktop e Node.js):

```powershell
npm run dev
```

O script [`scripts/dev.mjs`](scripts/dev.mjs) faz tudo em sequência:

1. Cria o `.env` a partir do `.env.example` com senhas aleatórias (se não existir) e completa variáveis faltantes (`JWT_SECRET_DEV`, `OLLAMA_MODEL`).
2. Abre o Docker Desktop se ele estiver parado e aguarda ficar pronto.
3. Gera `infra/mosquitto/passwords` a partir das senhas MQTT do `.env` (se não existir).
4. Sobe todos os containers (`docker-compose.yml` + `docker-compose.dev.yml`).
5. Instala as dependências do `frontend-dev` (se faltar) e inicia o Vite com recarga automática em http://localhost:5173.

`Ctrl+C` encerra o Vite e para os containers (os dados são mantidos).

| Comando | Ação |
|---|---|
| `npm run dev` | Sobe tudo + frontend com hot reload |
| `npm run up` | Sobe só os containers |
| `npm run logs` | Logs dos containers |
| `npm run ps` | Estado dos containers |
| `npm run stop` | Para os containers |
| `npm run down` | Remove os containers |

Equivalente manual, sem o script:

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

Na primeira execução:

- o PostgreSQL cria as tabelas (`schema.sql`) e os equipamentos (`seed.sql`);
- o worker `ai-jobs` percebe que não há modelo treinado, **gera a base e treina** sozinho (cerca de 2 a 3 minutos); a inferência aguarda o modelo;
- a API baixa o modelo do assistente (`llama3.2:3b`, cerca de 2 GB) para o volume `ollama_data`.

Crie os usuários de login do ambiente de desenvolvimento (as senhas são pedidas no terminal, mínimo de 12 caracteres):

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm -v "${PWD}/services/api/seed_users.py:/app/seed_users.py" api-dev python seed_users.py
```

Acesse **http://localhost:8080**.

Recomenda-se pelo menos 8 GB de memória para o Docker/WSL2.

### Bancos criados antes destas funções

Aplique as migrações em `infra/postgres/migrations` (comandos do motor e tabela de jobs de IA):

```powershell
Get-Content infra/postgres/migrations/001-motor-commands.sql | docker compose exec -T postgres psql -U factory_app -d smart_factory_dev
Get-Content infra/postgres/migrations/002-ai-jobs.sql | docker compose exec -T postgres psql -U factory_app -d smart_factory_dev
```

### Desenvolvimento do frontend (opcional)

Para editar as telas com recarga automática:

```powershell
cd frontend-dev
npm install
npm run dev
```

Acesse http://localhost:5174.

### Gerar dados e treinar pela linha de comando (opcional)

```powershell
python ai/generate_dataset.py --motors 200 --cycles 5000 --failure-modes geral,rolamento,superaquecimento,eletrica
python ai/train_models.py --window-features
```

## 9. Endpoints principais

| Endpoint | Descrição |
|---|---|
| `GET /health` | Estado da API e das conexões |
| `GET /api/devices` | Equipamentos cadastrados |
| `GET /api/factory/state` | Estado atual da fábrica |
| `GET /api/ai/predictions` | Previsões disponíveis da IA |
| `GET /api/ai/predictions/motor-01` | Previsão do Motor 01 |
| `GET /api/alerts` | Alertas armazenados |
| `GET /api/commands/history` | Histórico de comandos |
| `POST /api/conveyor/command` | Solicitação de ON/OFF da esteira |
| `POST /api/motor/command` | Injeção de falha (`INJECT_FAULT`) ou manutenção (`MAINTENANCE`) do motor |
| `GET /api/assistant/status` | Estado do LLM local (baixando, carregando, pronto) |
| `POST /api/assistant/chat` | Pergunta ao assistente (resposta em streaming) |
| `GET /api/insights` | Histórico de saúde/RUL, alertas e ações do motor |
| `GET /api/history?device_id=&period=` | Histórico de sensores no InfluxDB (15m, 1h, 6h, 24h) |
| `GET /api/model/info` | Modelo em uso: versão, métricas, importância, previsto × real |
| `POST /api/jobs/generate` | Enfileira a geração da base (`q.jobs.generate`) |
| `POST /api/jobs/train` | Enfileira um treino (`q.jobs.train`) |
| `GET /api/jobs` | Jobs de IA e seu andamento |
| `POST/PUT/DELETE /api/devices` | Cadastro de dispositivos (admin) |
| `WS /ws/factory` | Atualizações em tempo real |

Documentação interativa da API:

http://localhost:8000/docs

## 10. Serviços disponíveis

| Serviço | Endereço local |
|---|---|
| Frontend (login e todas as telas) | http://localhost:8080 |
| API de desenvolvimento (com login) | http://localhost:8001/docs |
| FastAPI | http://localhost:8000 |
| Swagger | http://localhost:8000/docs |
| RabbitMQ Management | http://localhost:15672 |
| InfluxDB | http://localhost:8086 |

As interfaces de gerenciamento exigem as credenciais configuradas no ambiente.

## 11. Testes realizados

As seguintes funcionalidades foram verificadas durante o desenvolvimento:

- Comunicação entre simulador, MQTT e RabbitMQ.
- Recebimento de telemetrias em tempo real.
- Geração contínua de previsões pela IA.
- Exibição dos indicadores de IA no dashboard.
- Funcionamento do gêmeo digital 3D.
- Controle de ON/OFF da esteira.
- Conexão entre FastAPI e PostgreSQL.
- Consulta dos equipamentos cadastrados.
- Persistência de comandos no PostgreSQL.
- Criação e resolução de alertas de manutenção.
- Inicialização do PostgreSQL a partir dos scripts SQL.

Para o teste da criação de alertas, foi publicada uma previsão artificial identificada como evento de teste. Isso validou o fluxo de persistência sem representar uma falha industrial real.

## 12. Limitações e melhorias futuras

- Validar os modelos com dados coletados de equipamentos reais.
- Implementar confirmação de execução dos comandos pelos dispositivos.
- Adicionar autenticação e controle de permissões.
- Disponibilizar gerenciamento de regras de monitoramento pela interface.
- Implementar reconhecimento de alertas por usuários.
- Expandir o registro de auditoria.
- Aprimorar a lógica de abertura e resolução de alertas para evitar oscilações.
- Automatizar o treinamento e a disponibilização dos modelos.

## 13. Contexto acadêmico

Projeto desenvolvido para estudo e demonstração dos conceitos de Smart Factory, AIoT, sistemas distribuídos, comunicação assíncrona, bancos de dados e aprendizado de máquina.

A solução utiliza equipamentos simulados e dados sintéticos, com foco na integração de tecnologias e na demonstração de manutenção preditiva.