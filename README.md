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

Foram gerados aproximadamente 1.000.000 de registros sintéticos, simulando a evolução do desgaste de 200 motores ao longo de seus ciclos operacionais.

Entre as variáveis utilizadas estão:

- Temperatura do motor.
- Vibração.
- Corrente elétrica.
- Temperatura ambiente.
- Umidade.
- Estado operacional.
- Quantidade de ciclos.

### Modelos

Foram treinados dois modelos baseados em HistGradientBoostingRegressor:

**Modelo RUL**

Estima a vida útil restante do motor em ciclos.

**Modelo Health**

Estima o percentual de saúde do equipamento.

### Resultados obtidos

| Métrica | Modelo RUL | Modelo Health |
|---|---:|---:|
| MAE | 209,81 ciclos | 2,04 pontos percentuais |
| RMSE | 262,70 ciclos | 2,78 pontos percentuais |
| R² | 0,9666 | 0,9917 |

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

### Gerar os dados e treinar a IA

Crie um ambiente virtual Python:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Instale as dependências necessárias:

```powershell
python -m pip install numpy pandas scikit-learn joblib matplotlib
```

Gere o dataset sintético:

```powershell
python ai/generate_dataset.py --motors 200 --cycles 5000 --seed 42
```

Treine os modelos:

```powershell
python ai/train_models.py
```

Os arquivos serão gerados em `ai/models`:

- `rul_model.joblib`
- `health_model.joblib`
- `metadata.json`

Os modelos treinados não estão incluídos no repositório e precisam ser gerados antes de iniciar o serviço de inferência.

### Inicializar os serviços

Na pasta principal do projeto:

```powershell
docker compose up -d --build
```

Na primeira inicialização de um banco PostgreSQL vazio, os arquivos `schema.sql` e `seed.sql` criam automaticamente as tabelas e os equipamentos.

Na primeira vez, a API também baixa o modelo do assistente (`llama3.2:3b`, cerca de 2 GB) para o volume `ollama_data`. O progresso aparece na aba Assistente e em `GET /api/assistant/status`.

### Inicializar o frontend

Em outro terminal:

```powershell
cd frontend
npm install
npm run dev
```

Acesse:

http://localhost:5173

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
| `GET /api/assistant/status` | Estado do LLM local (baixando, carregando, pronto) |
| `POST /api/assistant/chat` | Pergunta ao assistente (resposta em streaming) |
| `WS /ws/factory` | Atualizações em tempo real |

Documentação interativa da API:

http://localhost:8000/docs

## 10. Serviços disponíveis

| Serviço | Endereço local |
|---|---|
| Dashboard | http://localhost:5173 |
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