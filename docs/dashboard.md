# Dashboard API — preparação do frontend, etapa 3

Implementação do contrato [P3 aprovado](pre-frontend-contracts.md), após o estado
operacional da [etapa 2](decisions/0010-operational-state.md). As três rotas são
consultas, acessíveis a ADMIN, OPERATOR e VIEWER ativos com JWT **access**. Refresh
token e chave de dispositivo não autorizam essas consultas. Usuário e role são
consultados novamente no banco, conforme a autenticação existente.

## Resumo

`GET /api/v1/dashboard/summary`, sem parâmetros de consulta.

Retorna `as_of` UTC, `total_machines`, `normal`, `fault`, `offline`, `maintenance`,
`unknown` e `critical_events_24h`. As cinco classes operacionais somam o total de
máquinas. UNKNOWN corresponde a evidência insuficiente; não é um novo enum no banco.

Eventos críticos são todos os registros com severity CRITICAL e started_at no
intervalo `[as_of - 24h, as_of)`, incluindo reconhecidos, COLOR_RED e ALARM_SOUND.
Não se restringem aos tipos do WebSocket. Ocorrências futuras ficam fora dessa janela.

## Eventos por período

`GET /api/v1/dashboard/events-by-period`

Obrigatórios: `start_date`, `end_date` com timezone e `bucket=hour|day`.
O início deve preceder o fim. Opcionais: `machine_id`, `event_type`, `severity`.
As datas são normalizadas para UTC. Um exemplo de consulta é:

```text
/api/v1/dashboard/events-by-period?start_date=2026-11-14T00:30:00Z&end_date=2026-11-14T03:15:00Z&bucket=hour
```

A resposta tem `as_of`, `start_date`, `end_date`, `bucket`, `items`. Cada item tem
`start`, `end`, `count`. O exemplo forma quatro intervalos: 00:30–01:00,
01:00–02:00, 02:00–03:00 e 03:00–03:15 UTC. Os limites são inclusivos no início
e exclusivos no fim, sem duplicar eventos nas fronteiras. Intervalos vazios
aparecem com zero. Datas futuras explicitamente solicitadas são consultadas.

Máximo de 200 intervalos, inclusive os parciais nas extremidades. Excesso retorna
422, sem truncamento ou troca de granularidade. Datas iguais, invertidas, sem
timezone, filtros inválidos e parâmetros desconhecidos também retornam 422.
Máquina inexistente com ID válido retorna série com zeros.

## Estado das máquinas

`GET /api/v1/dashboard/machine-status`

Filtros opcionais `machine_id` e `status=NORMAL|FAULT|OFFLINE|MAINTENANCE|UNKNOWN`.
Paginação `limit=50` (1–200), `offset=0` (0–BIGINT máximo). Ordenação por ID interno
da máquina crescente. Retorna `{as_of, total, limit, offset, items}`. `total` é
contado **depois dos filtros e antes da paginação**; permanece correto mesmo quando
offset ultrapassa o último item. Os dispositivos de uma máquina não consomem
posições adicionais na página.

Cada item expõe os campos aprovados de `OperationalMachine`, incluindo cadastro,
estado calculado, motivo, falha, disponibilidade e evidências de eventos/dispositivos.
O marcador interno de contexto não é exposto. Dados do cadastro são atuais;
IDs, UUIDs e datas das evidências preservam a ocorrência.

Prioridade: manutenção cadastrada, falha conhecida, dispositivos ativos todos
offline, recuperação com dispositivo online; demais casos têm operacional null.
Heartbeat não prova conectividade e ONLINE isolado não prova NORMAL. Leituras
não atualizam cadastro, eventos ou fila de alertas.

## Consistência, erros e limites

Cada resposta executa **uma instrução PostgreSQL** de dados. Resumo e filtros da
listagem compartilham a agregação SQL de estado sobre as mesmas evidências da
etapa 2; a montagem dos itens reutiliza o serviço operacional. Testes confrontam
as 36 combinações de cadastro, falha e conectividade para evitar divergência entre
contadores, filtros e itens. Contagem, seleção da página e suas evidências usam
o mesmo snapshot, mesmo se outra transação fizer commit durante a resposta.

`as_of` vem de `statement_timestamp()` do banco e é referência da consulta,
não cursor/replay. Requisições distintas podem observar alterações distintas.
Ao reconectar WebSocket, consultar novamente a API REST.

Ausência/invalidade de credencial: 401. Falha de banco/configuração: 503 sanitizado;
não substituir falha por contadores zero ou sucesso vazio. Payloads antigos de
máquinas/eventos/leituras permanecem inalterados. Novas rotas estão em `/docs`.

Não há novas dependências, configurações ou migrations nesta etapa. A migration
0004 continua obrigatória. As consultas de estado agregam a frota elegível no banco;
paginação limita máquinas retornadas, sem prometer limite de dispositivos por
máquina ou desempenho de produção. Não foi realizado ensaio de carga.

Implantação e validação local: [deployment.md](deployment.md) e
[testing.md](testing.md). Administração de alertas/configurações e fila de testes
continuam reservadas às etapas 4 e 5; frontend ainda não implementado.
