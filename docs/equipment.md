# Fase 3 — máquinas, dispositivos e heartbeat

Contrato aprovado pelo usuário. Não há migration nova nem dependência adicional.
Models, relações, índices e constraints da Fase 1 são reutilizados. Autenticação,
RBAC e sessões da Fase 2 permanecem em uso.

## Endpoints

| Método | Rota | Resultado |
| --- | --- | --- |
| POST | `/api/v1/machines` | 201, MachineRead |
| GET | `/api/v1/machines` | 200, lista de MachineRead |
| GET | `/api/v1/machines/{id}` | 200, MachineRead |
| PATCH | `/api/v1/machines/{id}` | 200, MachineRead |
| DELETE | `/api/v1/machines/{id}` | 204, sem corpo |
| POST | `/api/v1/devices` | 201, DeviceRead |
| GET | `/api/v1/devices` | 200, lista de DeviceRead |
| GET | `/api/v1/devices/{id}` | 200, DeviceRead |
| PATCH | `/api/v1/devices/{id}` | 200, DeviceRead |
| DELETE | `/api/v1/devices/{id}` | 204, sem corpo |
| POST | `/api/v1/devices/heartbeat` | 200, DeviceRead |

CRUD exige access token Bearer de usuário ativo. ADMIN cria, altera e exclui.
ADMIN, OPERATOR e VIEWER podem consultar. A role é consultada no banco pela
dependency existente; refresh token e chave de dispositivo não autorizam CRUD.
Listagens retornam arrays em ordem de ID; não há paginação nesta fase.

IDs de rota e `DeviceCreate.machine_id` são IDs internos BIGINT positivos.
`serial_number` e `device_uid` são identificadores textuais distintos e únicos.
Não há criação automática de máquina ou dispositivo.

## Criação e atualização

MachineCreate recebe serial_number, name, block, corridor, status e description
opcional. Status é obrigatório: NORMAL, FAULT, OFFLINE ou MAINTENANCE.

DeviceCreate recebe machine_id, device_uid, device_name, firmware_version opcional
e is_active (default true aprovado). `last_seen_at` pertence apenas à saída.

PATCH modifica somente campos fornecidos. Campos omitidos são preservados;
description e firmware_version podem ser limpos com null. Campos obrigatórios
não aceitam null explícito. PATCH vazio mantém o registro. Campos desconhecidos,
id, created_at, updated_at e last_seen_at não podem ser escritos pelo cliente.

A reassociação é permitida via PATCH do dispositivo. O machine_id histórico de
leituras/eventos permanece intocado. Esta fase não cria leituras nem eventos.

## Exclusão e erros

DELETE faz exclusão física apenas quando não existem referências. FKs continuam
com ON DELETE RESTRICT e ON UPDATE RESTRICT. Não há cascade nem remoção de histórico.
Desativação de dispositivo é feita com PATCH is_active=false, não com DELETE.

- 401: credencial ausente/inválida, token inadequado ou usuário inativo.
- 403: role insuficiente; no heartbeat, dispositivo inativo.
- 404: máquina/dispositivo inexistente, incluindo associação com machine_id ausente.
- 409: duplicidade, referência impedindo exclusão ou máquina incompatível no heartbeat.
- 422: payload ou ID inválido.
- 503: banco/configuração de autenticação indisponível.

Violações esperadas são tratadas em savepoint; a transação pode ser revertida sem
expor SQL, parâmetros ou traceback ao cliente. Routers adaptam HTTP, services
aplicam regras e repositories executam consultas.

## Heartbeat

Configure a variável existente `DEVICE_API_KEY` no `.env`, sem versionar seu valor.
Compose exige a variável e a encaminha ao backend. A requisição usa o header
`X-API-Key`, comparado em tempo constante. Não usa credenciais de usuário.
A chave é compartilhada pelo host/dispositivos: ela não constitui identidade
criptográfica individual de cada dispositivo. Não foi criada tabela de chaves.

JSON de entrada:

- `device_uid`: obrigatório; identifica dispositivo cadastrado.
- `serial_number`: obrigatório; identifica a máquina associada.
- `firmware_version`: opcional; quando omitido preserva o valor, null é rejeitado.
- `status`: opcional, aceita somente ONLINE; não persistido.
- `uptime_seconds`: opcional, inteiro não negativo; não persistido.

Não aceita os nomes ambíguos device_id/machine_id do exemplo conceitual como
substitutos dos identificadores textuais. Não aceita horário enviado pelo cliente.
O servidor verifica cadastro, atividade e associação e atualiza last_seen_at em
UTC. A linha do dispositivo é bloqueada durante heartbeat e atualizações para
serializar a operação com reassociação/desativação. Retorna DeviceRead.

Nenhum status de máquina é alterado automaticamente. Não há detecção offline,
scheduler, evento, alerta ou integração de hardware.

## Validação

```powershell
docker compose build backend
docker compose run --rm --no-deps backend python -m pytest -q
docker compose up -d --wait backend
docker compose exec -T backend python -m alembic current
docker compose exec -T backend python -m alembic check
docker compose ps
```

`test_equipment.py` usa a aplicação real e PostgreSQL em schema transacional
isolado, removido por rollback. Não gera dados fictícios nas tabelas públicas.
Inclui todos os métodos CRUD, roles, inativos, duplicidade, FKs RESTRICT,
reassociação histórica, validação de campos internos, UTC e autenticação do
heartbeat. A revisão Alembic continua `0002_domain_models`.
