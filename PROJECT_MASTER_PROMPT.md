# PROJECT MASTER PROMPT — Machine Monitor

## 1. Papel do agente de desenvolvimento

Atue como um **Engenheiro de Software Sênior Full Stack e Especialista em Sistemas Embarcados**, com experiência prática em:

- C/C++ para Arduino Mega 2560;
- Arduino Framework / PlatformIO;
- aquisição e processamento de sinais de sensores;
- sistemas embarcados e comunicação serial com computador host;
- Python;
- FastAPI;
- PostgreSQL;
- SQLAlchemy / SQLModel;
- React;
- TypeScript;
- Vite;
- WebSocket;
- Docker e Docker Compose;
- APIs REST;
- autenticação JWT;
- sistemas de monitoramento industrial;
- telemetria;
- automação de alertas;
- testes unitários, integração e end-to-end;
- documentação técnica.

O objetivo é construir um protótipo funcional, organizado e evolutivo de monitoramento de uma máquina de testes utilizando um **Arduino Mega 2560**, um **Sensor de Cor TCS230/TCS3200** e um **Módulo Sensor de Som KY-037**.

O projeto deve permanecer modular, mas a V1 será implementada e validada exclusivamente com esse conjunto de hardware. O Arduino Mega 2560 se comunicará com o computador host por **USB/Serial**, e um serviço no host encaminhará as leituras e eventos para a API.

---

# 2. Objetivo geral

Construir um sistema capaz de:

1. Capturar dados de um sensor de cor instalado em frente ao painel luminoso de uma máquina.
2. Capturar áudio proveniente de um buzzer/alarme da máquina.
3. Identificar quando o painel está exibindo a cor **AZUL**.
4. Identificar quando o painel está exibindo a cor **VERMELHA**.
5. Identificar um sinal sonoro agudo característico de falha.
6. Correlacionar a detecção da cor vermelha com o som de alarme.
7. Classificar o estado da máquina.
8. Registrar leituras relevantes.
9. Registrar eventos de falha.
10. Transmitir informações para uma API.
11. Armazenar os dados em banco relacional.
12. Exibir informações em uma aplicação web local.
13. Atualizar eventos importantes em tempo real.
14. Enviar mensagens automáticas de alerta.
15. Evitar alertas duplicados durante uma mesma ocorrência.
16. Operar a V1 com Arduino Mega 2560, TCS230/TCS3200 e KY-037, utilizando comunicação USB/Serial com o computador host.

---

# 3. Cenário físico

A máquina de testes possui:

- um painel luminoso;
- um buzzer/alarme;
- identificação física;
- número de série;
- localização dentro de uma instalação.

Estados esperados do painel:

```text
AZUL      = funcionamento normal
VERMELHO  = possível falha
```

O buzzer emite um som agudo quando ocorre um problema.

A combinação mais importante é:

```text
PAINEL VERMELHO
+
ALARME SONORO DETECTADO
=
FALHA CONFIRMADA
```

---

# 4. Arquitetura geral

Implementar a seguinte arquitetura lógica:

```text
┌───────────────────────────────────────┐
│             MÁQUINA                   │
│                                       │
│  Painel luminoso       Buzzer         │
└─────────┬─────────────────┬───────────┘
          │                 │
          ▼                 ▼
   Sensor de Cor      Sensor Sonoro
          │                 │
          └────────┬────────┘
                   ▼
        Arduino Mega 2560
                   │
             Processamento
                   │
             Fault Detector
                   │
              USB / Serial
                   │
                   ▼
          Serial Ingest / Bridge
                   │
                   ▼
               FastAPI
          ┌────────┼────────┐
          │        │        │
          ▼        ▼        ▼
      PostgreSQL WebSocket AlertService
          │        │        │
          │        │    Telegram/E-mail
          │        │
          └────┬───┘
               ▼
          React Frontend
```

---

# 5. Princípios de arquitetura

O desenvolvimento deve obedecer aos seguintes princípios:

## 5.1 Separação de responsabilidades

O hardware embarcado deve ser responsável por:

- aquisição dos sensores;
- filtragem básica;
- classificação local;
- correlação de sinais;
- criação de eventos;
- transmissão para o servidor.

O backend deve ser responsável por:

- autenticação;
- persistência;
- consulta;
- regras de negócio complementares;
- controle de alertas;
- WebSockets;
- geração de informações para o dashboard.

O frontend deve ser responsável por:

- visualização;
- interação do usuário;
- configuração;
- exibição de histórico;
- notificações visuais.

---

# 6. Stack tecnológica

## Firmware

```text
Linguagem: C/C++
Placa: Arduino Mega 2560
Sensor de cor: TCS230/TCS3200
Sensor sonoro: KY-037
Comunicação com host: USB/Serial
Build recomendado: PlatformIO
```

## Backend

```text
Python
FastAPI
SQLAlchemy ou SQLModel
Pydantic
Alembic
Uvicorn
```

## Banco

```text
PostgreSQL
```

## Frontend

```text
React
TypeScript
Vite
React Router
Recharts
Axios ou Fetch API
```

## Infraestrutura

```text
Docker
Docker Compose
Git
.env
```

## Comunicação

```text
REST
HTTP/HTTPS
WebSocket
JSON
```

---

# 7. Estrutura do repositório

Criar:

```text
machine-monitor/
│
├── firmware/
│   ├── include/
│   ├── src/
│   │   ├── sensors/
│   │   │   ├── ColorSensor.h
│   │   │   ├── ColorSensor.cpp
│   │   │   ├── SoundSensor.h
│   │   │   └── SoundSensor.cpp
│   │   │
│   │   ├── detection/
│   │   │   ├── FaultDetector.h
│   │   │   └── FaultDetector.cpp
│   │   │
│   │   ├── communication/
│   │   │   ├── ApiClient.h
│   │   │   └── ApiClient.cpp
│   │   │
│   │   ├── storage/
│   │   │   ├── OfflineBuffer.h
│   │   │   └── OfflineBuffer.cpp
│   │   │
│   │   ├── config/
│   │   │   └── DeviceConfig.h
│   │   │
│   │   └── main.cpp
│   │
│   ├── test/
│   └── platformio.ini
│
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── database/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   ├── alerts/
│   │   ├── websocket/
│   │   └── main.py
│   │
│   ├── tests/
│   ├── alembic/
│   ├── requirements.txt
│   └── Dockerfile
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── layouts/
│   │   ├── services/
│   │   ├── hooks/
│   │   ├── contexts/
│   │   ├── types/
│   │   ├── utils/
│   │   └── main.tsx
│   │
│   ├── package.json
│   └── Dockerfile
│
├── database/
│   ├── init/
│   └── seed/
│
├── docs/
│   ├── architecture.md
│   ├── api.md
│   ├── hardware.md
│   ├── database.md
│   ├── testing.md
│   └── deployment.md
│
├── docker-compose.yml
├── .env.example
├── .gitignore
├── README.md
└── PROJECT_MASTER_PROMPT.md
```

---

# 8. Firmware — arquitetura interna

O firmware não deve concentrar toda a lógica dentro de `main.cpp`.

Criar interfaces independentes.

## ColorSensor

Responsabilidades:

- inicializar sensor;
- ler dados RGB;
- normalizar valores;
- classificar cor;
- retornar qualidade da leitura.

Interface lógica:

```cpp
struct ColorReading {
    int red;
    int green;
    int blue;
    float confidence;
};

enum class DetectedColor {
    BLUE,
    RED,
    UNKNOWN
};
```

Métodos esperados:

```cpp
bool begin();
ColorReading read();
DetectedColor classify(const ColorReading& reading);
```

---

# 9. Sensor de cor — TCS230/TCS3200

O sensor utilizado na V1 será o **TCS230/TCS3200**. Sua saída é uma frequência proporcional à intensidade luminosa selecionada pelos filtros internos. Os pinos `S2` e `S3` selecionam o conjunto de fotodiodos para vermelho, azul, verde ou clear, enquanto `S0` e `S1` controlam a escala da frequência de saída.

O firmware deverá medir a frequência/período do pino `OUT` para cada filtro de cor e produzir valores normalizados de vermelho, verde e azul.

A classificação não deve depender somente da comparação simples entre R, G e B.

Implementar:

1. leitura RGB;
2. normalização;
3. calibração;
4. filtro de ruído;
5. limites configuráveis;
6. classificação;
7. estado UNKNOWN quando não houver confiança suficiente.

Adicionar parâmetros configuráveis:

```text
RED_MIN
BLUE_MIN
COLOR_CONFIDENCE_MIN
COLOR_CONFIRMATION_COUNT
```

A mudança de estado deve exigir múltiplas leituras consecutivas.

Exemplo:

```text
RED
RED
RED
RED
RED

=> confirmar RED
```

Isso reduz falsos positivos.

---

# 10. Sensor sonoro — KY-037

O sensor utilizado na V1 será o **Módulo Sensor de Som Microfone KY-037**.

O módulo oferece:

- saída analógica `AO`, usada para observar a variação de amplitude do sinal;
- saída digital `DO`, acionada quando o nível ultrapassa o limiar ajustado no potenciômetro do módulo.

Objetivo da V1:

Detectar de forma confiável a ocorrência do buzzer/alarme da máquina em ambiente controlado, usando principalmente **amplitude, limiar, duração e padrão temporal**.

Não assumir que o KY-037 fornece uma medição calibrada em dB. Não registrar `sound_db` como valor físico confiável sem procedimento de calibração com instrumento de referência.

Também não tornar FFT ou frequência dominante um requisito obrigatório da V1. Caso a saída analógica e a taxa de amostragem obtida no Arduino Mega permitam uma análise experimental útil, essa análise pode ser implementada como melhoria opcional e deve ser validada com sinais reais do buzzer.

Fluxo mínimo:

```text
KY-037 AO/DO
    ↓
Amostragem / leitura de limiar
    ↓
Filtro temporal
    ↓
Amplitude acima do limite?
    ↓
Persistiu pelo tempo configurado?
    ↓
ALARM_DETECTED
```

Estrutura sugerida:

```cpp
struct SoundReading {
    int analogValue;
    bool digitalTrigger;
    float normalizedAmplitude;
    unsigned long durationMs;
    bool alarmDetected;
};
```

Parâmetros configuráveis:

```text
ALARM_ANALOG_THRESHOLD
ALARM_MIN_DURATION_MS
ALARM_CONFIRMATION_COUNT
ALARM_COOLDOWN_MS
```

A calibração deverá coletar amostras do buzzer real e de ruídos comuns do ambiente para definir os limites.

Se os testes demonstrarem que o KY-037 não consegue distinguir o alarme dos ruídos com precisão suficiente, registrar essa limitação como resultado técnico da validação; não mascarar o problema com valores arbitrários.

---

# 11. Máquina de estados

Criar `FaultDetector`.

Estados:

```text
NORMAL
SUSPECT
FAULT_ACTIVE
RECOVERY
```

Fluxo principal:

```text
NORMAL
   │
   │ RED detectado
   ▼
SUSPECT
   │
   │ som válido dentro da janela
   ▼
FAULT_ACTIVE
   │
   │ sinais normalizados por período configurável
   ▼
RECOVERY
   │
   ▼
NORMAL
```

---

# 12. Regra principal de correlação

Parâmetro:

```text
FAULT_CORRELATION_WINDOW_MS
```

Valor inicial sugerido:

```text
3000 ms
```

A regra conceitual será:

```text
color == RED
AND
alarm_detected == true
AND
difference(timestamp_color, timestamp_alarm) <= FAULT_CORRELATION_WINDOW_MS
```

Resultado:

```text
FAULT_CONFIRMED
```

O valor deve ser configurável e calibrado em campo.

---

# 13. Heartbeat do dispositivo

Cada dispositivo deve transmitir periodicamente um heartbeat.

Exemplo:

```json
{
  "device_id": "MEGA2560-001",
  "machine_id": "MACHINE-001",
  "status": "ONLINE",
  "firmware_version": "0.1.0",
  "uptime_seconds": 21033
}
```

Endpoint:

```text
POST /api/v1/devices/heartbeat
```

Permitir ao sistema detectar dispositivos offline.

---

# 14. Estratégia de armazenamento no dispositivo

Não enviar todas as amostras brutas para o servidor.

Criar três categorias:

## Telemetria

Dados resumidos enviados em intervalos configuráveis.

## Eventos

Mudanças relevantes de estado.

## Falhas

Eventos críticos enviados imediatamente.

---

# 15. Buffer e tolerância a indisponibilidade

Na V1, o Arduino Mega 2560 envia dados ao computador host por USB/Serial. O serviço de ingestão no host deverá tolerar indisponibilidade temporária da API ou do banco sem descartar eventos críticos.

Fluxo:

```text
Evento recebido via Serial
    ↓
API disponível?
    │
 ┌──┴───┐
 SIM    NÃO
 │       │
 ▼       ▼
API    BUFFER LOCAL NO HOST
         │
         ▼
    API restaurada
         │
         ▼
       reenviar
```

Cada evento deverá possuir UUID para garantir idempotência. O Arduino não precisa implementar persistência offline complexa na V1.

O backend deve impedir gravação duplicada do mesmo UUID.

---

# 16. Modelo de dados

Implementar inicialmente as seguintes tabelas.

## users

```text
id
name
email
password_hash
role
is_active
created_at
updated_at
```

Roles iniciais:

```text
ADMIN
OPERATOR
VIEWER
```

---

## machines

```text
id
serial_number
name
block
corridor
description
status
created_at
updated_at
```

Status:

```text
NORMAL
FAULT
OFFLINE
MAINTENANCE
```

---

## devices

```text
id
machine_id
device_uid
device_name
firmware_version
last_seen_at
is_active
created_at
updated_at
```

---

## sensor_readings

```text
id
uuid
machine_id
device_id
timestamp
color
red_value
green_value
blue_value
color_confidence
sound_detected
sound_amplitude
sound_trigger
sound_duration_ms
created_at
```

---

## events

```text
id
uuid
machine_id
device_id
event_type
severity
started_at
ended_at
color
sound_detected
sound_amplitude
sound_duration_ms
message
acknowledged
acknowledged_by
acknowledged_at
created_at
```

Tipos:

```text
COLOR_RED
ALARM_SOUND
FAULT_CONFIRMED
FAULT_RECOVERED
DEVICE_OFFLINE
DEVICE_ONLINE
```

Severity:

```text
INFO
WARNING
CRITICAL
```

---

## alert_recipients

```text
id
name
channel
destination
is_active
created_at
updated_at
```

Channels:

```text
TELEGRAM
EMAIL
WHATSAPP
SMS
```

---

## alerts

```text
id
event_id
recipient_id
channel
status
sent_at
error_message
created_at
```

Status:

```text
PENDING
SENT
FAILED
```

---

# 17. API REST

Usar prefixo:

```text
/api/v1
```

---

# 18. Autenticação

Criar:

```text
POST /api/v1/auth/login
POST /api/v1/auth/refresh
GET  /api/v1/auth/me
```

Utilizar:

```text
JWT Access Token
JWT Refresh Token
Password Hashing
```

Nunca armazenar senha em texto puro.

---

# 19. Máquinas

Criar:

```text
GET    /api/v1/machines
POST   /api/v1/machines
GET    /api/v1/machines/{id}
PUT    /api/v1/machines/{id}
DELETE /api/v1/machines/{id}
```

---

# 20. Dispositivos

Criar:

```text
GET  /api/v1/devices
GET  /api/v1/devices/{id}
POST /api/v1/devices/heartbeat
```

---

# 21. Sensor readings

Criar:

```text
POST /api/v1/readings
GET  /api/v1/readings
GET  /api/v1/readings/{id}
```

Filtros:

```text
machine_id
start_date
end_date
color
sound_detected
limit
offset
```

---

# 22. Eventos

Criar:

```text
POST /api/v1/events
GET  /api/v1/events
GET  /api/v1/events/{id}
POST /api/v1/events/{id}/acknowledge
```

Filtros:

```text
machine_id
event_type
severity
acknowledged
start_date
end_date
```

---

# 23. Dashboard API

Criar:

```text
GET /api/v1/dashboard/summary
GET /api/v1/dashboard/events-by-period
GET /api/v1/dashboard/machine-status
```

Exemplo de summary:

```json
{
  "total_machines": 10,
  "normal": 8,
  "fault": 1,
  "offline": 1,
  "critical_events_24h": 3
}
```

---

# 24. WebSocket

Criar:

```text
WS /api/v1/ws/events
```

Eventos que devem ser propagados:

```text
FAULT_CONFIRMED
FAULT_RECOVERED
DEVICE_OFFLINE
DEVICE_ONLINE
```

Mensagem exemplo:

```json
{
  "type": "FAULT_CONFIRMED",
  "machine_id": "MACHINE-001",
  "timestamp": "2026-10-01T14:32:18Z",
  "severity": "CRITICAL"
}
```

---

# 25. Identificação do dispositivo

O dispositivo deve utilizar uma credencial própria.

Header sugerido:

```text
X-Device-Key
```

O backend deve validar a chave antes de aceitar telemetria.

Não utilizar credenciais administrativas no firmware.

---

# 26. Sistema de alertas

Criar interface genérica:

```python
class AlertProvider:
    async def send(self, message: str, destination: str):
        ...
```

Implementações:

```text
TelegramProvider
EmailProvider
WhatsAppProvider
SMSProvider
```

Implementar inicialmente:

```text
Telegram
Email
```

Manter os outros providers preparados como extensão futura.

---

# 27. Regra de disparo de alerta

Enviar alerta apenas quando ocorrer:

```text
FAULT_CONFIRMED
```

Não enviar novo alerta a cada leitura enquanto a máquina continuar em falha.

Fluxo:

```text
FAULT_CONFIRMED
    ↓
criar evento
    ↓
enviar alerta
    ↓
FAULT_ACTIVE
    ↓
não reenviar
```

Somente após:

```text
FAULT_RECOVERED
```

a máquina poderá gerar uma nova ocorrência independente.

---

# 28. Template de alerta

Utilizar estrutura semelhante a:

```text
⚠ ALERTA DE FALHA

Máquina: {machine_name}
Número de série: {serial_number}
Local: Bloco {block} — Corredor {corridor}

Painel: VERMELHO
Alarme sonoro: DETECTADO
Nível sonoro relativo: {sound_amplitude}

Horário: {timestamp}

Favor verificar o equipamento imediatamente.
```

---

# 29. Cooldown

Adicionar:

```text
ALERT_COOLDOWN_SECONDS
```

Mesmo havendo falhas de comunicação ou reprocessamento, o servidor não deve disparar mensagens duplicadas.

---

# 30. Frontend

Criar aplicação web responsiva.

Rotas:

```text
/login
/dashboard
/machines
/machines/:id
/events
/history
/alerts
/settings
```

---

# 31. Login

Tela contendo:

```text
E-mail
Senha
Entrar
```

Após autenticação, armazenar sessão de maneira segura e redirecionar para dashboard.

---

# 32. Dashboard

Exibir:

```text
Quantidade total de máquinas
Máquinas normais
Máquinas em falha
Máquinas offline
Eventos críticos nas últimas 24h
```

Exibir gráfico de eventos por período.

Utilizar gráfico de barras/histograma.

---

# 33. Status visual

Usar convenção:

```text
NORMAL      → verde
FAULT       → vermelho
OFFLINE     → cinza
MAINTENANCE → amarelo
```

Nunca depender exclusivamente de cor.

Adicionar também:

```text
ícone
texto
badge
```

para acessibilidade.

---

# 34. Página de máquinas

Tabela:

```text
Nome
Número de série
Localização
Status
Último contato
Ações
```

---

# 35. Detalhes da máquina

Exibir:

```text
status atual
última leitura
último evento
histórico de eventos
gr gráfico temporal
estado do dispositivo
data do último heartbeat
```

---

# 36. Página de eventos

Tabela:

```text
Data/Hora
Máquina
Evento
Severidade
Status
Reconhecido por
```

Filtros:

```text
máquina
severidade
período
tipo de evento
```

---

# 37. Atualização em tempo real

Quando WebSocket receber:

```text
FAULT_CONFIRMED
```

frontend deverá:

1. atualizar o card da máquina;
2. atualizar contadores;
3. adicionar evento à lista;
4. mostrar notificação visual;
5. opcionalmente emitir som no navegador.

---

# 38. Configuração de alertas

Tela `/alerts` deve permitir:

```text
listar destinatários
adicionar destinatário
editar destinatário
ativar/desativar
selecionar canal
realizar teste de envio
```

---

# 39. Docker Compose

Criar serviços:

```text
postgres
backend
frontend
```

Estrutura conceitual:

```yaml
services:
  postgres:
    image: postgres

  backend:
    build: ./backend
    depends_on:
      - postgres

  frontend:
    build: ./frontend
    depends_on:
      - backend
```

Não expor senhas diretamente no arquivo.

Utilizar `.env`.

---

# 40. Variáveis de ambiente

Criar `.env.example` com:

```text
POSTGRES_DB=
POSTGRES_USER=
POSTGRES_PASSWORD=
DATABASE_URL=

JWT_SECRET=
JWT_ALGORITHM=
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=

TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

SMTP_HOST=
SMTP_PORT=
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=

DEVICE_API_KEY=
```

---

# 41. Logs

Backend deve possuir logs estruturados.

Registrar:

```text
login
falha de autenticação
evento recebido
falha criada
alerta enviado
alerta falhou
dispositivo offline
dispositivo online
erro interno
```

Nunca registrar:

```text
senhas
tokens
JWT completos
chaves de API
```

---

# 42. Tratamento de erro

Padronizar respostas:

```json
{
  "error": {
    "code": "MACHINE_NOT_FOUND",
    "message": "Machine not found"
  }
}
```

---

# 43. Segurança

Implementar:

```text
password hashing
JWT
refresh token
RBAC
API key para dispositivos
CORS configurável
validação Pydantic
rate limiting onde necessário
SQL parametrizado via ORM
proteção de secrets
```

---

# 44. RBAC

Permissões sugeridas:

## ADMIN

```text
CRUD máquinas
CRUD usuários
CRUD destinatários
ver eventos
reconhecer eventos
alterar configurações
```

## OPERATOR

```text
ver máquinas
ver eventos
reconhecer eventos
```

## VIEWER

```text
somente leitura
```

---

# 45. Testes do firmware

Criar testes para:

```text
classificação RED
classificação BLUE
UNKNOWN
filtro de ruído
correlação temporal
entrada em FAULT_ACTIVE
saída de FAULT_ACTIVE
buffer offline
```

---

# 46. Testes backend

Utilizar pytest.

Cobrir:

```text
login
JWT
permissões
CRUD máquinas
criação de leitura
criação de evento
idempotência de UUID
alertas
acknowledge
heartbeat
WebSocket
```

---

# 47. Testes frontend

Cobrir minimamente:

```text
login
dashboard
carregamento da tabela
filtros
recebimento WebSocket
mudança de status
```

---

# 48. Teste de integração principal

Criar cenário automatizado:

```text
Sensor simulado
    ↓
RED
    ↓
Alarm = true
    ↓
Firmware cria FAULT_CONFIRMED
    ↓
POST /events
    ↓
PostgreSQL
    ↓
AlertService
    ↓
WebSocket
    ↓
Frontend
```

O teste será considerado aprovado somente se todos os componentes propagarem corretamente o evento.

---

# 49. Simulador de sensores

Antes de depender do hardware real, criar simulador.

Localização sugerida:

```text
tools/simulator/
```

Deve permitir gerar:

```text
NORMAL
RED_ONLY
SOUND_ONLY
FAULT
RECOVERY
DEVICE_OFFLINE
```

Isso será essencial para desenvolver backend e frontend antes da eletrônica final.

---

# 50. Dados simulados

Exemplo:

```json
{
  "uuid": "...",
  "machine_id": "MACHINE-001",
  "timestamp": "2026-10-01T18:00:00Z",
  "color": "RED",
  "red_value": 220,
  "green_value": 35,
  "blue_value": 31,
  "color_confidence": 0.96,
  "sound_detected": true,
  "sound_amplitude": 0.82,
  "sound_duration_ms": 650
}
```

---

# 51. Estratégia de implementação

Não desenvolver tudo simultaneamente.

Executar por fases.

---

# FASE 0 — Bootstrap - OK

Entregáveis:

```text
repositório
estrutura de pastas
README
.env.example
Docker Compose
PostgreSQL funcionando
backend mínimo funcionando
frontend mínimo funcionando
```

Critério:

```text
docker compose up
```

deve iniciar banco, backend e frontend.

---

# FASE 1 — Backend base

Criar:

```text
FastAPI
PostgreSQL
SQLAlchemy/SQLModel
Alembic
models
schemas
repositories/services
```

Critério:

```text
GET /health
```

retorna:

```json
{
  "status": "ok"
}
```

---

# FASE 2 — Autenticação

Criar login, JWT, refresh e RBAC.

Criar usuário administrador inicial por seed.

---

# FASE 3 — Máquinas e dispositivos

Implementar CRUD e heartbeat.

---

# FASE 4 — Telemetria

Implementar endpoint de readings.

Criar filtros e paginação.

---

# FASE 5 — Eventos

Implementar eventos, severidade, acknowledge e UUID idempotente.

---

# FASE 6 — AlertService

Implementar:

```text
Telegram
E-mail
```

Adicionar prevenção de duplicidade.

---

# FASE 7 — WebSocket

Transmitir eventos críticos em tempo real.

---

# FASE 8 — Frontend

Criar:

```text
login
layout
dashboard
machines
events
alerts
```

---

# FASE 9 — Simulador

Criar ferramenta capaz de simular dispositivos.

Executar cenários normais e falhas.

---

# FASE 10 — Integração física com Arduino Mega 2560

Implementar e validar o protótipo físico utilizando exclusivamente:

```text
Arduino Mega 2560
Sensor de Cor TCS230/TCS3200
Módulo Sensor de Som Microfone KY-037
```

## 10.1 Objetivo inicial

Fazer o Arduino Mega 2560:

```text
ler TCS230/TCS3200
ler KY-037
normalizar leituras
classificar BLUE / RED / UNKNOWN
detectar ALARM_DETECTED
correlacionar vermelho + alarme
produzir eventos
enviar dados por USB/Serial
```

## 10.2 TCS230/TCS3200

Implementar driver isolado para o sensor de cor.

Responsabilidades:

- configurar `S0`, `S1`, `S2` e `S3`;
- medir o sinal no pino `OUT`;
- coletar componentes R, G e B;
- normalizar os valores;
- aplicar calibração;
- classificar `BLUE`, `RED` ou `UNKNOWN`;
- permitir ajuste dos limites sem reescrever a lógica principal.

Não fixar um pinout arbitrário como regra arquitetural. Definir os pinos em um arquivo de configuração do firmware e documentar o mapeamento utilizado na montagem real.

## 10.3 KY-037

Implementar driver isolado usando:

```text
AO → entrada analógica do Mega
DO → entrada digital opcional
```

Utilizar a saída analógica para obter uma medida relativa de amplitude e a saída digital como sinal auxiliar de limiar.

O algoritmo inicial deverá trabalhar com:

```text
amplitude relativa
limiar configurável
duração
leituras consecutivas
cooldown
```

Não tratar o valor do KY-037 como dB calibrado. FFT/frequência dominante não é requisito obrigatório da Fase 10.

## 10.4 Comunicação com o computador host

O Arduino Mega 2560 não possui Wi-Fi nativo. Na V1, utilizar a conexão USB/Serial existente da placa.

Formato recomendado: mensagens JSON delimitadas por linha (`JSON Lines`).

Exemplo:

```json
{
  "device_id": "MEGA2560-001",
  "machine_id": "MACHINE-001",
  "color": "RED",
  "red_value": 812,
  "green_value": 190,
  "blue_value": 221,
  "sound_detected": true,
  "sound_amplitude": 0.82,
  "status": "FAULT",
  "event_uuid": "<uuid>"
}
```

Criar no computador host um pequeno serviço de ingestão serial responsável por:

```text
abrir a porta serial
validar mensagens
reconectar quando necessário
encaminhar leituras/eventos para FastAPI
manter buffer local quando a API estiver indisponível
evitar duplicidade usando UUID
```

Esse serviço pode ser implementado em Python e deve permanecer separado da lógica principal da API.

## 10.5 Critérios de conclusão da fase

A Fase 10 só estará concluída quando:

- [ ] o Mega compilar sem erros;
- [ ] o TCS230/TCS3200 identificar azul, vermelho e desconhecido em condições de teste;
- [ ] o KY-037 detectar o buzzer com os limites calibrados para o ambiente de teste;
- [ ] a correlação vermelho + alarme gerar `FAULT_CONFIRMED`;
- [ ] o firmware transmitir mensagens estruturadas via Serial;
- [ ] o serviço de ingestão receber e validar essas mensagens;
- [ ] a API receber ao menos um evento real proveniente do Arduino;
- [ ] o banco persistir esse evento;
- [ ] o dashboard refletir o evento real.

---

# FASE 11 — Calibração

Criar modo de calibração.

Coletar amostras de:

```text
painel azul
painel vermelho
ambiente claro
ambiente escuro
buzzer real
conversação
ruído industrial
```

A partir desses dados determinar:

```text
limites do TCS230/TCS3200
confidence de cor
limiar analógico do KY-037
limiar digital do KY-037
duração mínima do alarme
janela de correlação
```

Não inventar valores definitivos antes da coleta real.

Caso seja testada análise de frequência experimental com o KY-037, documentar separadamente a taxa de amostragem, método, resultados e limitações.

---

# FASE 12 — Validação integrada

Executar testes reais de ponta a ponta:

```text
Máquina normal
→ dashboard NORMAL

Painel vermelho sem buzzer
→ não confirmar falha crítica

Buzzer sem vermelho
→ não confirmar falha crítica

Vermelho + buzzer
→ FAULT_CONFIRMED
→ persistência
→ WebSocket
→ dashboard em falha
→ alerta

Retorno ao normal
→ FAULT_RECOVERED
→ dashboard normal
```

Registrar falsos positivos, falsos negativos e latências observadas.

---

# 52. Critérios de aceite gerais

O protótipo só poderá ser considerado funcional quando:

- [ ] sensor de cor identificar corretamente azul e vermelho em ambiente controlado;
- [ ] KY-037 detectar o buzzer real com taxa de acerto aceitável no ambiente de teste e com limitações documentadas;
- [ ] correlação vermelho + alarme produzir evento de falha;
- [ ] eventos possuírem timestamp;
- [ ] eventos possuírem UUID;
- [ ] API receber dados do dispositivo;
- [ ] banco registrar os dados;
- [ ] dashboard apresentar status das máquinas;
- [ ] tabela apresentar histórico;
- [ ] WebSocket atualizar a interface em tempo real;
- [ ] Telegram receber alerta;
- [ ] e-mail receber alerta;
- [ ] alertas duplicados não sejam enviados continuamente;
- [ ] perda temporária da conexão Serial ou indisponibilidade da API não descarte eventos críticos já recebidos pelo serviço de ingestão;
- [ ] autenticação esteja funcionando;
- [ ] usuários tenham permissões distintas;
- [ ] aplicação possa iniciar por Docker Compose.

---

# 53. Métricas do protótipo

Registrar durante validação:

```text
taxa de acerto cor
falsos positivos cor
falsos negativos cor

taxa de acerto buzzer
falsos positivos buzzer
falsos negativos buzzer

latência sensor → API
latência API → dashboard
latência evento → alerta
```

---

# 54. Requisitos não funcionais

## Manutenibilidade

Código modular e legível.

## Observabilidade

Logs suficientes para diagnóstico.

## Segurança

Sem credenciais hardcoded.

## Resiliência

Sistema tolerante a perda temporária de rede.

## Evolução

Novos sensores devem poder ser adicionados sem reescrever toda arquitetura.

---

# 55. Convenções de código

## Python

Utilizar:

```text
type hints
PEP 8
docstrings onde necessário
funções pequenas
responsabilidade única
```

## C++

Utilizar:

```text
classes pequenas
interfaces claras
const correctness quando aplicável
enums em vez de magic numbers
configurações centralizadas
```

## TypeScript

Evitar:

```text
any
```

sempre que possível.

Criar tipos para respostas da API.

---

# 56. Regra para geração de código

Ao implementar qualquer módulo:

1. informar o objetivo;
2. informar arquivos criados/modificados;
3. implementar código completo;
4. não usar pseudocódigo quando código real for solicitado;
5. evitar placeholders desnecessários;
6. explicar como executar;
7. explicar como testar;
8. executar testes disponíveis;
9. corrigir erros encontrados;
10. manter compatibilidade com módulos existentes.

---

# 57. Regra de dependências

Antes de adicionar uma biblioteca:

1. verificar se é realmente necessária;
2. preferir biblioteca amplamente utilizada;
3. evitar dependências abandonadas;
4. registrar dependência no arquivo adequado;
5. documentar motivo quando não for óbvio.

---

# 58. Regra de backward compatibility

Quando uma API já estiver sendo usada pelo firmware ou frontend:

```text
não alterar silenciosamente contratos existentes
```

Se for necessária alteração incompatível:

```text
criar nova versão
```

Exemplo:

```text
/api/v2
```

---

# 59. Documentação obrigatória

Manter atualizados:

```text
README.md
docs/architecture.md
docs/api.md
docs/hardware.md
docs/database.md
docs/testing.md
docs/deployment.md
```

---

# 60. README mínimo

README deve explicar:

```text
o que é o projeto
arquitetura
pré-requisitos
como configurar
como iniciar
como testar
como executar simulador
como acessar frontend
como acessar Swagger
```

---

# 61. Swagger/OpenAPI

FastAPI deve disponibilizar documentação automática.

Durante desenvolvimento:

```text
/docs
/redoc
```

---

# 62. Health checks

Criar:

```text
GET /health
GET /ready
```

`/health` indica que processo está ativo.

`/ready` deve verificar dependências essenciais como banco.

---

# 63. Detecção de dispositivo offline

Backend deve considerar dispositivo offline quando:

```text
current_time - last_seen_at > DEVICE_OFFLINE_THRESHOLD
```

Parâmetro configurável.

Ao mudar para offline:

```text
DEVICE_OFFLINE
```

Ao retornar:

```text
DEVICE_ONLINE
```

---

# 64. Timestamp

Todos os timestamps devem ser armazenados em UTC.

Frontend converte para horário local do usuário.

---

# 65. Idempotência

Todo evento gerado pelo hardware deve possuir UUID.

Banco deverá ter índice/constraint unique.

Se mesmo evento for retransmitido devido a falha de rede:

```text
não criar duplicata
```

---

# 66. Paginação

Endpoints de listagem devem aceitar:

```text
limit
offset
```

Definir limite máximo para evitar consultas excessivas.

---

# 67. Índices de banco

Criar índices para consultas frequentes:

```text
sensor_readings.machine_id
sensor_readings.timestamp
events.machine_id
events.started_at
events.event_type
events.severity
devices.last_seen_at
```

---

# 68. Retenção de dados

O protótipo não deve assumir armazenamento infinito.

Preparar política configurável para:

```text
sensor_readings
```

Eventos críticos devem possuir retenção maior que telemetria ordinária.

Não implementar exclusão automática irreversível sem configuração explícita.

---

# 69. Futuras extensões previstas

Arquitetura deve permitir futuramente:

```text
MQTT
GSM/LTE
SMS
WhatsApp oficial
múltiplos sensores
múltiplas máquinas
monitoramento remoto
cloud deployment
OTA firmware update
metrics/Prometheus
Grafana
TLS mútuo
```

Esses recursos não pertencem obrigatoriamente à V1.

---

# 70. Definição da V1

A primeira versão funcional deve conter apenas o necessário para demonstrar o conceito de ponta a ponta:

```text
Arduino Mega 2560 ou simulador
TCS230/TCS3200
KY-037
Detecção de falha
FastAPI
PostgreSQL
React
Login
Dashboard
Histórico
WebSocket
Telegram
E-mail
Docker Compose
```

Evitar adicionar complexidade desnecessária antes dessa versão funcionar integralmente.

---

# 71. Ordem obrigatória de prioridade

Quando houver conflito entre funcionalidades, priorizar:

```text
1. funcionamento correto da detecção
2. integridade dos dados
3. confiabilidade da transmissão
4. prevenção de falsos alertas
5. segurança
6. observabilidade
7. experiência do usuário
8. funcionalidades adicionais
```

---

# 72. Primeira tarefa de implementação

Após ler completamente este arquivo, iniciar pela **FASE 0 — Bootstrap**.

Executar:

1. criar estrutura inicial do monorepo;
2. criar `.gitignore`;
3. criar `.env.example`;
4. criar backend FastAPI mínimo;
5. criar endpoint `/health`;
6. criar frontend React + TypeScript + Vite;
7. criar PostgreSQL no Docker Compose;
8. conectar backend ao PostgreSQL;
9. criar Dockerfiles;
10. criar README inicial;
11. validar `docker compose up`;
12. informar exatamente quais arquivos foram criados;
13. informar comandos de execução;
14. executar ou descrever testes de smoke test;
15. somente depois avançar para a FASE 1.

Não pular diretamente para funcionalidades avançadas.

---

# 73. Resposta esperada do agente ao iniciar o projeto

A resposta inicial deve conter:

```text
FASE ATUAL
OBJETIVO
DECISÕES TÉCNICAS
ARQUIVOS CRIADOS
CÓDIGO
COMO EXECUTAR
COMO TESTAR
RESULTADO ESPERADO
PRÓXIMA FASE
```

Não alterar as decisões arquiteturais deste documento sem explicar tecnicamente o motivo.

---

# 74. Regra final

O objetivo principal deste projeto não é apenas construir uma demonstração visual.

O sistema deve provar tecnicamente o fluxo completo:

```text
FENÔMENO FÍSICO
      ↓
SENSOR
      ↓
MICROCONTROLADOR
      ↓
PROCESSAMENTO
      ↓
DETECÇÃO
      ↓
REDE
      ↓
API
      ↓
BANCO
      ↓
EVENTO
      ↓
ALERTA
      ↓
INTERFACE WEB
```

Cada camada deve ser testável de forma independente.

O projeto deverá sempre evoluir mantendo esta separação.

---

# 75. Resultado esperado

Ao término da V1, um operador deverá conseguir observar a máquina em funcionamento normal e, quando o painel ficar vermelho e o alarme sonoro correspondente for detectado, o sistema deverá automaticamente:

1. identificar a condição;
2. confirmar a falha;
3. gerar um UUID para a ocorrência;
4. transmitir o evento;
5. registrar no PostgreSQL;
6. atualizar o dashboard;
7. exibir a máquina em estado de falha;
8. registrar horário, cor e dados do som;
9. enviar alerta aos responsáveis;
10. impedir alertas repetitivos da mesma ocorrência;
11. registrar a recuperação da máquina quando os sinais normalizarem.

Este comportamento representa o **critério principal de sucesso do protótipo**.
