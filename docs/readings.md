# Fase 4 — telemetria

Contrato aprovado pelo usuário após auditoria da Fase 3. Reutiliza a tabela
`sensor_readings`, models e schemas da Fase 1. Não há dependência ou migration nova.

## API

| Método | Rota | Autenticação | Resposta |
| --- | --- | --- | --- |
| POST | `/api/v1/readings` | X-API-Key / DEVICE_API_KEY | 201 SensorReadingRead |
| GET | `/api/v1/readings` | access JWT; ADMIN, OPERATOR, VIEWER | 200 array SensorReadingRead |
| GET | `/api/v1/readings/{id}` | access JWT; ADMIN, OPERATOR, VIEWER | 200 SensorReadingRead ou 404 |

A chave compartilhada não identifica criptograficamente cada dispositivo. Não há
substituição por JWT no POST nem por API key/refresh JWT nos GETs. O usuário deve
existir e estar ativo; a role é consultada no banco em cada requisição.

O POST recebe `SensorReadingCreate`: uuid, machine_id, device_id, timestamp,
color, red_value, green_value, blue_value, color_confidence, sound_detected,
sound_amplitude, sound_duration_ms e sound_trigger opcional/nullable. UUID é
obrigatório e fornecido pelo cliente. IDs são BIGINT internos positivos, distintos
do UUID e do device_uid. `id` e `created_at` são gerados pelo banco; campos extras
ou internos enviados pelo cliente são rejeitados.

Timestamp exige fuso e é convertido para UTC. Não há limite artificial de idade
ou de data futura. Cores: BLUE, RED, UNKNOWN. RGB é INTEGER não negativo (até
2147483647, sem limite 255). Confidence fica entre 0 e 1. Amplitude permanece
bruta, sem normalização nem CHECK 0..1, mas deve ser finita. NaN, infinitos e
overflow numérico retornam 422; valores finitos negativos ou acima de 1 continuam
aceitos. Duração é BIGINT não negativo.

## Integridade e erros

- 401: credencial ausente, inválida ou finalidade incorreta do JWT; usuário inativo.
- 403: dispositivo inativo no POST ou role insuficiente na consulta.
- 404: leitura consultada, dispositivo ou máquina informada inexistente.
- 409: UUID repetido, associação incompatível ou conflito de referência.
- 422: payload, ID, filtros, datas ou paginação inválidos.
- 503: configuração de autenticação ou banco indisponível.

A leitura deve corresponder à associação atual do dispositivo no momento da
inserção. Uma leitura atrasada para a associação anterior retorna 409. Leituras
já persistidas mantêm seu machine_id após reassociação. O POST bloqueia a linha
do dispositivo com FOR UPDATE, como PATCH/DELETE/heartbeat, até o fim da transação.
Duplicidade é resolvida pela constraint UNIQUE, inclusive para requisições
concorrentes: não sobrescreve dados. Erros de integridade são tratados em savepoint.

Leituras não alteram status de máquina, last_seen_at, firmware ou atividade do
dispositivo. Somente heartbeat atualiza last_seen_at neste fluxo. Não geram
eventos, alertas ou mensagens WebSocket.

## Filtros e paginação

Filtros opcionais combinados por AND:

- `machine_id`: igualdade com o ID histórico; ID inexistente retorna array vazio.
- `start_date` e `end_date`: limites inclusivos sobre timestamp da leitura, com
  fuso obrigatório e conversão UTC. Intervalo invertido retorna 422.
- `color`: BLUE, RED ou UNKNOWN.
- `sound_detected`: booleano, incluindo false.
- `limit`: padrão 50, mínimo 1, máximo 200; fora da faixa retorna 422.
- `offset`: padrão 0, faixa 0..9223372036854775807 (limite técnico BIGINT do
  PostgreSQL). Valores fora da faixa retornam 422 antes da consulta.

Ordenação: timestamp DESC, id DESC, com LIMIT/OFFSET executados no PostgreSQL.
Sem envelope ou contagem total. Empates de timestamp são resolvidos pelo ID.
Paginação por offset não constitui snapshot: inserções concorrentes podem
deslocar páginas entre requisições.

## Validação

```powershell
docker compose build backend
docker compose run --rm --no-deps backend python -m pytest -q
docker compose up -d --wait backend
docker compose exec -T backend python -m alembic current
docker compose exec -T backend python -m alembic check
docker compose ps
```

`tests/test_readings.py` usa os routers reais, JWT/API key e PostgreSQL em schema
transacional removido por rollback. Não cadastra máquinas, dispositivos ou
leituras fictícias nas tabelas públicas. Consulte os resultados em testing.md.
