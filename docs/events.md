# Fase 5 — eventos

Contrato aprovado pelo usuário. Reutiliza events, seus índices, FKs RESTRICT e
constraints da migration 0002_domain_models. Sem novas dependências ou migrations.

## Endpoints

| Método | Rota | Credencial/permissão | Resposta |
| --- | --- | --- | --- |
| POST | /api/v1/events | X-API-Key (DEVICE_API_KEY) | 201 novo; 200 retransmissão idêntica |
| GET | /api/v1/events | access JWT; ADMIN, OPERATOR, VIEWER | 200 array de EventRead |
| GET | /api/v1/events/{id} | access JWT; ADMIN, OPERATOR, VIEWER | 200 EventRead |
| POST | /api/v1/events/{id}/acknowledge | access JWT; ADMIN, OPERATOR | 200 EventRead |

Usuário ativo e role atual são consultados no banco. Refresh tokens não autorizam
essas operações. API key não substitui JWT nem JWT substitui API key na ingestão.
A chave compartilhada não constitui identidade criptográfica individual.

## Entrada e severidade

EventRequest recebe uuid, machine_id, device_id, event_type, severity, started_at,
message e os opcionais ended_at, color, sound_detected, sound_amplitude,
sound_duration_ms. Campos opcionais omitidos equivalem a null. UUID é obrigatório
e fornecido pelo produtor; IDs de máquina/dispositivo são BIGINT internos positivos.

Tipos: COLOR_RED, ALARM_SOUND, FAULT_CONFIRMED, FAULT_RECOVERED, DEVICE_OFFLINE,
DEVICE_ONLINE. Severidade é informada pelo produtor: INFO, WARNING ou CRITICAL.
Não há inferência automática nem tabela de correspondência tipo/severidade.

Datas exigem fuso, são convertidas para UTC; ended_at não pode preceder started_at.
Datas cuja conversão ultrapasse o intervalo representável retornam 422, inclusive
nos filtros. Isso não impõe limite de idade ou de data futura.
Amplitude aceita números finitos brutos, inclusive negativos e acima de 1;
NaN/infinitos/overflow retornam 422. Duração é BIGINT não negativo. Cores opcionais
são BLUE, RED ou UNKNOWN. Campos extras são rejeitados.
Message não aceita o caractere NUL (U+0000), incompatível com TEXT no PostgreSQL;
retorna 422 antes da persistência. Acentos, emojis e quebras de linha são preservados.

id, created_at e todos os campos acknowledged* pertencem ao servidor. O schema
EventCreate interno da Fase 1 permanece disponível para persistência, mas não é
usado como entrada pública de ingestão.

## Idempotência

- UUID novo: 201 e uma ocorrência persistida.
- UUID existente com os mesmos dados normalizados de ocorrência: 200, retornando
  o registro atual, incluindo eventual reconhecimento posterior.
- UUID existente com dados diferentes: 409, sem sobrescrever.
- Campos de reconhecimento não entram na comparação; nenhuma atualização de
  ocorrência, encerramento ou exclusão é exposta nesta fase.

Para novas ocorrências, dispositivo deve estar ativo e associado à máquina
informada. A linha do dispositivo é bloqueada na transação, como no PATCH e
heartbeat. Leituras e eventos anteriores conservam sua associação histórica.
Uma retransmissão idêntica continua válida após reassociação, desde que o
dispositivo permaneça ativo. Evento novo para a associação anterior retorna 409.

A constraint uq_events_uuid e INSERT ON CONFLICT DO NOTHING protegem contra
concorrência. Após um conflito de inserção, a transação lê e compara a ocorrência
persistida. Não há geração automática de UUID nem duplicação em retry.

## Reconhecimento

Não enviar corpo na requisição de acknowledge. O servidor define acknowledged,
acknowledged_by com o usuário autenticado e acknowledged_at em UTC.
Bloqueio FOR UPDATE serializa reconhecimentos concorrentes; a primeira gravação
confirmada prevalece. Repetições retornam 200 sem mudar responsável ou horário.
Reconhecer não encerra o evento, não representa recuperação e não muda Machine.status.

## Filtros e paginação

machine_id (histórico), event_type, severity e acknowledged são filtros de igualdade.
start_date/end_date incidem sobre started_at, são inclusivos, exigem fuso e aceitam
apenas intervalo ordenado. Filtros são combinados por AND; nenhuma correspondência
retorna []. Booleano false é aplicado como filtro.

limit padrão 50, entre 1 e 200; offset padrão 0, entre 0 e 9223372036854775807.
Ordenação started_at DESC, id DESC, com paginação no PostgreSQL. Sem total/envelope.
Inserções concorrentes podem deslocar páginas entre consultas por offset.

## Erros e limites

401 credenciais inválidas/ausentes, token inadequado ou usuário inativo;
403 role insuficiente ou dispositivo inativo; 404 registro não encontrado;
409 UUID divergente, associação incompatível ou conflito de referência;
422 entrada inválida; 503 configuração/banco indisponível.

Erros de validação das rotas de eventos retornam detail como lista de diagnósticos
com loc, type e msg. Input e ctx são omitidos para evitar ecoar valores não
serializáveis (por exemplo, infinito originado de 1e309), independentemente da
categoria do erro. O tratamento de autenticação permanece separado.

Não há alterações automáticas em Machine.status, heartbeat, firmware ou atividade
de dispositivo. Não são geradas leituras, WebSockets, eventos derivados de readings
ou detecção de offline/falha. Hardware, bridge e dashboard não fazem parte desta fase.

Desde a Fase 6.2, novos FAULT_CONFIRMED podem criar alertas PENDING na mesma
transação, sem envio externo. A ingestão também bloqueia a máquina para ordenar
ciclos entre dispositivos. Configuração inválida da fila pode retornar 503 com
rollback. Contrato e cooldown: [alert-queue.md](alert-queue.md).

## Testes

test_events.py usa PostgreSQL em schema transacional removido por rollback.
test_event_concurrency.py usa conexões independentes em schema privado com nome
gerado por UUID; confirma dados somente nesse schema e o remove ao terminar,
usando downgrade da migration e DROP SCHEMA sem CASCADE. Nunca altera tabelas
públicas. Os limites de espera desse teste servem apenas para detectar bloqueios.

Comandos de validação e resultados: [testing.md](testing.md).
