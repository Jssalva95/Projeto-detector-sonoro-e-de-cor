# Modelagem aprovada — Fase 1

Esta proposta detalha lacunas da seção 16 do PROJECT_MASTER_PROMPT.md.
Decisões aprovadas pelo usuário, com a alteração explícita de aceitar amplitude
sonora bruta. Implementação: `0002_domain_models`, models e schemas de domínio.

## Decisões propostas

- `id`: BIGINT identity, chave primária interna. Não confundir com o `uuid` de
  eventos/leituras nem com `device_uid`. Exemplos textuais como MACHINE-001 não
  seriam PKs; o mapeamento desses exemplos para a API precisa de confirmação.
- Textos: TEXT, sem comprimentos arbitrários. Campos listados são NOT NULL,
  exceto os explicitamente marcados com `?` abaixo.
- Datas: TIMESTAMPTZ; aplicação opera em UTC. `created_at` tem default now().
  `updated_at` recebe now() na criação e é atualizado pelo ORM em alterações;
  escritas SQL externas deverão atualizar esse campo explicitamente.
- Enums: TEXT com CHECK nomeado, usando somente os valores da especificação.
  Evita criar tipos ENUM PostgreSQL adicionais, sem alterar valores públicos.
- FKs: ON DELETE RESTRICT e ON UPDATE RESTRICT; nenhum cascade de exclusão.
  Registros com `is_active` podem ser desativados, sem eliminar histórico.
- Não inferir NORMAL, ONLINE ou outro estado: o chamador informa os estados.
- `is_active`: default true; `acknowledged`: default false.
- UUIDs: tipo UUID do PostgreSQL, NOT NULL e UNIQUE; sem geração automática no
  servidor para substituir o identificador do evento recebido.

## Colunas propostas

`?` significa nullable. Demais colunas são obrigatórias.

| Tabela | Colunas e tipos |
| --- | --- |
| users | id BIGINT PK; name TEXT; email TEXT; password_hash TEXT; role TEXT; is_active BOOLEAN; created_at TIMESTAMPTZ; updated_at TIMESTAMPTZ |
| machines | id BIGINT PK; serial_number TEXT; name TEXT; block TEXT; corridor TEXT; description TEXT?; status TEXT; created_at TIMESTAMPTZ; updated_at TIMESTAMPTZ |
| devices | id BIGINT PK; machine_id BIGINT FK; device_uid TEXT; device_name TEXT; firmware_version TEXT?; last_seen_at TIMESTAMPTZ?; is_active BOOLEAN; created_at TIMESTAMPTZ; updated_at TIMESTAMPTZ |
| sensor_readings | id BIGINT PK; uuid UUID UNIQUE; machine_id BIGINT FK; device_id BIGINT FK; timestamp TIMESTAMPTZ; color TEXT; red_value INTEGER; green_value INTEGER; blue_value INTEGER; color_confidence DOUBLE PRECISION; sound_detected BOOLEAN; sound_amplitude DOUBLE PRECISION; sound_trigger BOOLEAN?; sound_duration_ms BIGINT; created_at TIMESTAMPTZ |
| events | id BIGINT PK; uuid UUID UNIQUE; machine_id BIGINT FK; device_id BIGINT FK; event_type TEXT; severity TEXT; started_at TIMESTAMPTZ; ended_at TIMESTAMPTZ?; color TEXT?; sound_detected BOOLEAN?; sound_amplitude DOUBLE PRECISION?; sound_duration_ms BIGINT?; message TEXT; acknowledged BOOLEAN; acknowledged_by BIGINT FK?; acknowledged_at TIMESTAMPTZ?; created_at TIMESTAMPTZ |
| alert_recipients | id BIGINT PK; name TEXT; channel TEXT; destination TEXT; is_active BOOLEAN; created_at TIMESTAMPTZ; updated_at TIMESTAMPTZ |
| alerts | id BIGINT PK; event_id BIGINT FK; recipient_id BIGINT FK; channel TEXT; status TEXT; sent_at TIMESTAMPTZ?; error_message TEXT?; created_at TIMESTAMPTZ |

Os campos sonoros/de cor de events seriam opcionais porque eventos de
dispositivo offline/online não necessariamente possuem leituras de sensores.
sound_trigger seria opcional porque a saída DO do KY-037 é auxiliar/opcional.

## Relações ORM e chaves estrangeiras propostas

- Machine.devices ↔ Device.machine: machines.id → devices.machine_id (1:N).
- Machine.readings ↔ SensorReading.machine; Device.readings ↔ SensorReading.device.
- Machine.events ↔ Event.machine; Device.events ↔ Event.device.
- User.acknowledged_events ↔ Event.acknowledged_user: users.id → events.acknowledged_by.
- Event.alerts ↔ Alert.event: events.id → alerts.event_id.
- AlertRecipient.alerts ↔ Alert.recipient: alert_recipients.id → alerts.recipient_id.

**Decisão aprovada:** permitir reassociar um dispositivo a outra máquina.
A modelagem mantém `machine_id` da leitura/evento como histórico da ocorrência e
FKs independentes, sem impor que sempre coincida com a máquina atual do dispositivo.
Essa consistência seria validada na ingestão na fase correspondente.

## Unicidade, CHECKs e índices propostos

- PK em cada id; UNIQUE em sensor_readings.uuid e events.uuid (exigido).
- Proposta de UNIQUE adicionais: machines.serial_number, devices.device_uid,
  índice único lower(users.email). Não foram definidos explicitamente no mestre.
- CHECK dos valores de role, machine status, event_type, severity, channel e alert
  status, conforme listas da seção 16; color aceita BLUE, RED e UNKNOWN.
- CHECK para `color_confidence` entre 0 e 1 e duração não negativa; RGB não
  negativo, **sem assumir limite máximo 255**. `sound_amplitude` aceita valor bruto
  do sensor/ADC, sem CHECK de faixa e sem normalização nesta fase.
- Proposta de CHECK ended_at >= started_at quando ended_at estiver preenchido.
- Proposta de CHECK de reconhecimento: false com acknowledged_by/at nulos; true
  com ambos preenchidos. A semântica de usuários desativados não elimina histórico.
- Índices exigidos: sensor_readings.machine_id, sensor_readings.timestamp,
  events.machine_id, events.started_at, events.event_type, events.severity,
  devices.last_seen_at.
- Índices adicionais propostos em demais FKs para consultas e integridade referencial.
- Sem UNIQUE em alerts(event_id, recipient_id, channel) o alerts representará cada tentativa de envio.

## Limites do escopo após aprovação

Criar somente modelos, schemas de dados e migrations correspondentes às definições
aprovadas. Não criar autenticação, seeds, endpoints CRUD, ingestão ou envio de alertas.
Não criar campos extras para contornar ambiguidades.

## Aprovação registrada

O usuário aprovou tipos dos IDs, campos nullable, unicidade, índices, regras de
exclusão/atualização, reassociação de dispositivos e múltiplas tentativas em alerts.
A única alteração solicitada à proposta foi retirar a faixa 0..1 de
`sound_amplitude`. Os defaults e demais CHECKs da proposta foram mantidos.
