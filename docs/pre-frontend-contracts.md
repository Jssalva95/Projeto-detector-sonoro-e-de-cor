# Preparação da Fase 8 — contratos aprovados na etapa 1

Data: 2026-11-14. Base inspecionada: `405e508`.

**Status: P1–P8 aprovados integralmente pelo usuário em 2026-11-14.** A aprovação
inclui a coluna de contexto, sua inicialização, prioridade de estados, contratos
de consultas, identidade dos destinatários, tabela de testes e cooldown de 300s.
Aprovação de contrato não significa implementação concluída. A execução permanece
dividida nas etapas 2 a 5, agora implementadas e validadas. O frontend permanece
separado. Contratos da API em [dashboard.md](dashboard.md) e [alert-tests.md](alert-tests.md).

## 1. Evidências e limites já estabelecidos

- O PROJECT_MASTER_PROMPT.md, seções 23 e 30–38, prevê dashboard, histórico,
  configurações e administração web de destinatários. O roteiro resumido das
  fases não distribui todas essas dependências em tarefas de backend.
- [ADR 0004](decisions/0004-phase5-events.md): eventos não inferem Machine.status;
  reconhecer não significa recuperar. A ordem de consulta REST é temporal.
- [ADR 0006](decisions/0006-phase6-transactional-queue.md): ciclos de alerta usam
  a última transição persistida por ID e bloqueio por máquina, não started_at.
- [ADR 0007](decisions/0007-phase6-delivery-worker.md) e [worker](alert-worker.md):
  existem CLI, reserva durável e envio sem retry automático; não existe API web
  de destinatários. O destino é lido na reserva, sem snapshot em alerts.
- [Modelagem](database-proposal.md): dispositivo pode mudar de máquina; machine_id
  em eventos/leituras preserva a ocorrência. Não existe histórico de associações.
- [WebSocket](websocket.md): transmissão transitória após commit, sem replay;
  apenas quatro tipos críticos. O navegador recupera dados por REST.

Permanecem PostgreSQL, FastAPI, SQLAlchemy, IDs internos BIGINT, UUIDs de
ocorrências, UTC, JWT access com usuário ativo e role atual. Nenhuma mudança
retroativa nas respostas REST existentes, enums de domínio, fila ou eventos.
Novos contratos abaixo são aditivos e seguem a estrutura de models, schemas,
repositories/services e rotas. Sem frontend, firmware ou envio externo nesta etapa.

## 2. P1 — Estado operacional calculado no backend

### 2.1 Separar cadastro, falha e disponibilidade

Manter machines.status e seus endpoints exatamente como estão. Expor em novas
consultas `registered_status` com esse valor e `operational_status` calculado;
não sobrescrever o cadastro ao ingerir eventos. A interface deve distinguir os
dois, usando o operacional para indicadores e o cadastrado no formulário.

Dimensões independentes aprovadas:

- `fault_active`: boolean nullable. Último FAULT_CONFIRMED/FAULT_RECOVERED da
  máquina, por maior Event.id visível: true/false; sem transição, null.
- `availability`: ONLINE, OFFLINE ou UNKNOWN, somente no novo schema de resposta.
  Não é novo valor em MachineStatus ou em tabela existente.
- `maintenance`: registered_status == MAINTENANCE, decisão administrativa explícita.

Falha permanece por máquina, como o ciclo aprovado de alertas: recuperação de
outro dispositivo da mesma máquina encerra esse ciclo. Não mudar para ciclos
independentes por sensor nesta entrega. A saída mantém ID, UUID, started_at e
created_at da transição usada, mesmo se o produtor tiver enviado datas fora de ordem.

Os dados descrevem **último estado conhecido**, não comprovação física atual.
Eventos antigos já persistidos participam da dimensão de falha. Evento atrasado
novo participa pela ordem de persistência por máquina; isso é uma escolha explícita
de coerência com o ciclo existente, não uma garantia de cronologia física.
Replays idempotentes e reconhecimento não criam transição. COLOR_RED, ALARM_SOUND,
leituras e ended_at não alteram essas dimensões. Não reexecutar envios por leitura.

### 2.2 P2 — Disponibilidade e reassociação segura

Considerar somente dispositivos ativos atualmente associados à máquina.
Para cada um, usar seu último DEVICE_ONLINE/DEVICE_OFFLINE da associação/ativação
atual por maior Event.id. Nenhum evento elegível significa UNKNOWN.

| Dispositivos elegíveis | availability da máquina |
| --- | --- |
| Ao menos um ONLINE | ONLINE |
| Um ou mais e todos OFFLINE | OFFLINE |
| Nenhum, ou combinação OFFLINE/UNKNOWN sem ONLINE | UNKNOWN |

Não gerar DEVICE_OFFLINE pelo tempo decorrido. Heartbeat mostra last_seen_at,
mas não apaga um DEVICE_OFFLINE nem cria ONLINE por inferência. O heartbeat atual
não guarda a máquina histórica do contato: rotular a data como contato do dispositivo,
não contato comprovado da associação atual.

**Mudança adicional aprovada:** uma coluna técnica
`devices.status_event_id_floor BIGINT NOT NULL`, CHECK >= 0, sem FK. Ela registra
o maior ID de evento já observado para o dispositivo na redefinição do contexto;
0 significa nenhum evento anterior. Não é um ID de ocorrência a consultar.

- Na criação do dispositivo, valor 0.
- Ao mudar machine_id ou reativar dispositivo, sob o bloqueio existente do
  dispositivo, gravar max(events.id para device_id), ou 0. Não modificar eventos.
- Disponibilidade usa eventos com device_id/machine_id correspondentes e
  id > status_event_id_floor. Mudar nome/firmware ou repetir o mesmo vínculo
  não redefine o marcador. Eventos de falha por máquina não usam esse filtro.
- Migration aditiva inicializa dispositivos existentes com seu maior Event.id,
  impedindo interpretar associações antigas como atuais. Até novo evento de
  conectividade, a disponibilidade desses dispositivos será UNKNOWN.
- A migration deve impedir escrita concorrente durante o preenchimento. Testar
  reatribuição A→B→A, reativação e ingestão concorrente usando os mesmos bloqueios.
- Campo interno, não aceito em payload nem acrescentado a DeviceRead existente.

Esse marcador resolve a ausência de histórico sem inventar datas de associação
ou reutilizar updated_at (que também muda por heartbeat e outras edições).
O efeito de iniciar a disponibilidade como desconhecida foi aprovado expressamente.

### 2.3 Prioridade aprovada e ausência de dados

Avaliar nesta ordem, preservando as dimensões independentes na resposta:

| Condição | operational_status | reason |
| --- | --- | --- |
| maintenance | MAINTENANCE | REGISTERED_MAINTENANCE |
| fault_active == true | FAULT | ACTIVE_FAULT |
| availability == OFFLINE | OFFLINE | ALL_ACTIVE_DEVICES_OFFLINE |
| fault_active == false e availability == ONLINE | NORMAL | RECOVERED_AND_ONLINE |
| Demais casos | null | INSUFFICIENT_EVIDENCE |

Falha conhecida prevalece sobre indisponibilidade; mostrar ambas. Manutenção não
apaga a falha: o indicador de falha continua visível. ONLINE sozinho não comprova
normalidade; uma máquina sem transição de falha/recuperação pode permanecer null.
Não produzir evento de recuperação fictício para preencher a tela.
NORMAL/FAULT/OFFLINE do cadastro não substituem evidência operacional; permanecem
visíveis como informação cadastrada. Não criar UNKNOWN no enum de banco.

## 3. P3 — Dashboard API

Autorização: ADMIN, OPERATOR e VIEWER ativos com access JWT. Mesma implementação
de cálculo para resumo e listagem; sem filtro de role que mude contadores.
Consultas consistentes em um snapshot por resposta (consulta única ou transação
de leitura apropriada). Respostas de requisições distintas podem divergir por novas
gravações. `as_of` é a referência UTC da consulta, não cursor para reprodução futura.

### GET /api/v1/dashboard/summary

Sem parâmetros. Retorna objeto com:

- `as_of`: datetime UTC;
- `total_machines`, `normal`, `fault`, `offline`: contagens inteiras não negativas;
- `maintenance`, `unknown`: contagens adicionais aprovadas;
- `critical_events_24h`: eventos de severity CRITICAL com started_at no intervalo
  [as_of − 24 horas, as_of), incluindo reconhecidos e quaisquer tipos.

Invariante: total_machines = normal + fault + offline + maintenance + unknown.
`unknown` conta operational_status null, não uma falha de consulta. Banco indisponível
retorna erro, nunca contadores zero. Sem máquinas, contadores de máquinas são zero.
Severity CRITICAL não é sinônimo dos quatro tipos transmitidos via WebSocket.

### GET /api/v1/dashboard/events-by-period

Parâmetros obrigatórios: start_date, end_date e bucket (`hour` ou `day`).
Datas com timezone, normalizadas para UTC; start_date < end_date. Filtros opcionais:
machine_id, event_type e severity, usando os enums/IDs já existentes.

Resposta: `{as_of, start_date, end_date, bucket, items}`. Cada item contém
`start`, `end` UTC e `count`. Intervalos contíguos [start,end), alinhados a hora/dia
UTC, recortados nas extremidades solicitadas; incluir intervalos vazios com count 0.
Contar ocorrências por started_at, incluindo reconhecidas. Não agrupar por criação
do alerta ou horário do navegador. Ordem crescente por start.

Limite aprovado: até 200 intervalos por consulta; exceder retorna 422,
sem truncar, aumentar bucket ou mudar período silenciosamente. Esse limite de
consulta foi aprovado; não é um parâmetro físico ou default de período.
Filtro por machine_id válido sem resultados retorna série com zeros, como filtros REST.

### GET /api/v1/dashboard/machine-status

Filtros opcionais machine_id e status (NORMAL/FAULT/OFFLINE/MAINTENANCE/UNKNOWN,
onde UNKNOWN filtra null). Paginação limit=50, máximo 200, offset>=0, como consultas
existentes. Resposta `{as_of, total, limit, offset, items}`, total após filtros.
Ordem machine_id crescente; filtro sem correspondência retorna lista vazia.

Item: `machine_id`, `name`, `serial_number`, `block`, `corridor`, `registered_status`,
`operational_status`, `reason`, `fault_active`, `availability`,
`fault_evidence` (null ou event_id/uuid/event_type/started_at/created_at),
`device_evidence` (lista dos dispositivos ativos com device_id, availability,
last_seen_at e connection_event null ou evidência no mesmo formato).
Nomes e metadados são os atuais; evidências preservam as datas originais.

Não alterar arrays das listagens antigas. Novos envelopes só se aplicam às novas
rotas. Datas futuras não entram na janela de últimas 24h; continuam visíveis nas
consultas de período que explicitamente as incluírem. Sem valores fictícios.

## 4. P4 — API administrativa de destinatários e consultas de alertas

Todas as rotas desta seção e da seção 5 exigem ADMIN ativo. Não expor destinos
a OPERATOR/VIEWER. Clientes sem credencial recebem 401, sem role 403. Chave de
dispositivo não substitui JWT. Não implementar cadastro de usuários nesta entrega.

| Método/rota aprovada | Contrato |
| --- | --- |
| GET /api/v1/alert-recipients | Filtros channel/is_active, paginação 50/200; envelope total/limit/offset/items; ordem id crescente |
| GET /api/v1/alert-recipients/{id} | Destinatário por ID ou 404 |
| POST /api/v1/alert-recipients | name, channel EMAIL/TELEGRAM, destination, is_active (default true existente); 201 |
| PATCH /api/v1/alert-recipients/{id} | Campos parciais iguais, null recusado; 200 ou 409 por identidade vinculada |
| GET /api/v1/alerts | Filtros event_id/recipient_id/machine_id/channel/status; paginação 50/200; envelope total/limit/offset/items; ordem id decrescente |
| GET /api/v1/alerts/{id} | Tentativa de alerta real ou 404 |

Resposta do destinatário: id, name, channel, destination, is_active, created_at,
updated_at. Destino só em resposta administrativa autorizada, sem logs de payload.
Reutilizar validação de e-mail/Telegram; não adicionar WhatsApp/SMS. Registros legados
desses canais podem ser listados/desativados, mas não criados ou ativados pela nova API.
Não criar UNIQUE de destino: IDs distintos continuam independentes, como a CLI atual.

**Identidade vinculada:** quando existir qualquer alerts ou tentativa de teste
associada, bloquear mudança de channel/destination com 409; permitir nome e atividade.
Para trocar endereço, cadastrar novo destinatário e desativar o anterior. Antes de
haver tentativas, editar canal/destino é permitido. Sem DELETE; preservar as FKs RESTRICT.

A checagem e alteração devem bloquear o destinatário e ser coordenadas com os
writers de alerts/testes, revalidando elegibilidade após adquirir o bloqueio.
Padronizar ordem de locks e testar a corrida edição/enqueue/reserva; mera consulta
prévia sem lock não satisfaz o contrato. CLI e API devem compartilhar as mesmas
regras, sem exigir que o usuário pare workers para editar nome ou atividade.
Desativação não cancela envio já reservado, conforme contrato existente.

Resposta de tentativa real: campos de AlertRead existentes, com error_message
limitado a códigos sanitizados (valores legados desconhecidos viram código genérico).
SENT significa aceitação pelo provider, não confirmação na caixa do destinatário.
PENDING com attempt_started_at é iniciado/resultado ainda desconhecido, não uma
tentativa livre para reenviar. Não expor retry/reconciliação da CLI como API nesta etapa.

## 5. P5 — Teste de envio independente de eventos reais

### 5.1 Solicitação e idempotência

Rotas aprovadas:

- POST `/api/v1/alert-recipients/{id}/test`: corpo somente `{uuid}` obrigatório,
  UUID gerado pelo cliente para a ação; 202 para nova solicitação persistida.
- GET `/api/v1/alert-tests/{id}`: resultado por ID, somente ADMIN.
- GET `/api/v1/alert-tests`: filtros recipient_id/status, paginação 50/200,
  envelope total/limit/offset/items, ordem id decrescente.

Novo pedido exige destinatário ativo, canal habilitado/configurado e nenhuma
tentativa PENDING para esse destinatário. Confirmação de configuração não realiza
autenticação externa antecipada. Retornar 409 por inelegibilidade/em andamento,
503 por configuração indisponível, 422 por entrada inválida, 404 por ID inexistente.

Mesmo UUID, solicitante e destinatário: retornar 200 com o mesmo registro, sem
enviar novamente, mesmo depois de falha ou desativação do destinatário. UUID
existente com solicitante/destinatário divergentes: 409 sem revelar o registro.
Usuário inativo continua sem acesso. Repetição idempotente antecede cooldown e
elegibilidade de um novo pedido. Falha de resposta HTTP não autoriza novo UUID automático.

Variável aprovada, obrigatória quando o teste estiver disponível:
`ALERT_TEST_COOLDOWN_SECONDS=300` no ambiente local, sem default no código.
É uma configuração independente de ALERT_COOLDOWN_SECONDS de alertas reais.
Aplicar por recipient_id, usando horário do banco e qualquer pedido persistido;
novo pedido antecipado retorna 429 e Retry-After. Falha não elimina cooldown.
UUID replay não reinicia o intervalo. Não é rate limit global nem proteção completa
contra abuso por administrador; IDs distintos continuam independentes.

Texto fixo, sem assunto/destino/mensagem arbitrários na requisição:
assunto de e-mail `Machine Monitor — teste de envio`; corpo de saudação identifica
que é teste, não representa falha de máquina, e inclui UUID da solicitação.
Telegram usa a mesma finalidade. Não criar Event, Alert real ou disparo de sensores.

### 5.2 P6 — Persistência e execução aprovadas

Tabela `alert_test_attempts`, implementada na etapa 5 pela migration 0005:

| Coluna | Tipo/regra |
| --- | --- |
| id | BIGINT identity PK |
| uuid | UUID NOT NULL UNIQUE |
| recipient_id | BIGINT NOT NULL FK alert_recipients, RESTRICT |
| requested_by | BIGINT NOT NULL FK users, RESTRICT |
| channel | TEXT NOT NULL CHECK EMAIL/TELEGRAM, snapshot |
| destination | TEXT NOT NULL, snapshot de entrega; fora de logs/respostas de tentativa |
| status | TEXT NOT NULL CHECK PENDING/SENT/FAILED |
| created_at | TIMESTAMPTZ NOT NULL, relógio do banco |
| attempt_started_at | TIMESTAMPTZ nullable |
| sent_at | TIMESTAMPTZ nullable |
| error_message | TEXT nullable, somente código sanitizado |

FKs também ON UPDATE RESTRICT. Índices em recipient_id, requested_by e
(status,id). UNIQUE parcial em recipient_id WHERE status='PENDING' para impedir
pedidos simultâneos, além do lock do destinatário. CHECK: SENT exige marcador e
sent_at, sem erro; PENDING não tem sent_at/erro; FAILED exige marcador e código,
sem sent_at. Datas de conclusão não precedem a reserva; reserva não precede criação.
Relações ORM com AlertRecipient e User, sem cascade delete. Não adicionar event_id.
Resposta pública da tentativa contém todos os campos exceto destination.

Estender o worker separado existente para consumir esta fila, reutilizando
providers e timeouts. Não enviar dentro da requisição HTTP nem via BackgroundTasks.
Reservar/confirmar marcador antes de I/O; revalidar destinatário, canal habilitado e
solicitante ainda ADMIN ativo. Inelegível: FAILED com código fixo, sem envio.
Canal desabilitado permanece pendente sem reserva, como na fila atual.

Justiça aprovada entre filas: alternar alertas reais e testes quando ambas
tiverem trabalho, processando uma tentativa por vez; fila vazia não bloqueia a outra.
Reutilizar ALERT_POLL_INTERVAL_SECONDS, sem novo processo, broker ou scheduler.

Sem retry automático. Queda após reserva mantém PENDING iniciado para análise,
inclusive se o provider não chegou a ser chamado. Falha externa incerta vira
FAILED/delivery_unconfirmed se for possível persistir. Nenhuma garantia exactly-once.
Pedido pendente incerto bloqueia novo teste do destinatário até reconciliação.
Propor comando CLI específico de encerramento como FAILED/delivery_unconfirmed,
somente com declaração explícita de workers parados; nunca disparar reenvio nesse
comando. Novo teste é ação distinta, novo UUID e sujeito ao cooldown.

O worker e as duas filas devem continuar válidos após a migration. Não retirar
marcadores nem reabrir tentativas existentes durante implantação ou rollback.

## 6. P7 — /history e /settings na Fase 8

`/history`: manter rota própria para ADMIN/OPERATOR/VIEWER, com abas Eventos e
Leituras e consultas REST separadas. Reutilizar filtros e paginação existentes,
com períodos explícitos e horário local na apresentação. Não prometer timeline
unificada global a partir de duas páginas parciais. Detalhes de máquina reutilizam
esses componentes com machine_id. Amplitude é valor bruto, nunca dB calibrado.
Sem exportação, edição de leitura ou campos novos implícitos.

`/settings`: todos os papéis podem consultar a própria conta por /auth/me;
somente ADMIN consulta canais habilitados e parâmetros operacionais não secretos.
Nenhuma edição de SMTP, tokens, JWT, usuários, thresholds ou calibração nesta entrega.
Destinatários continuam em /alerts, sem duplicar sua administração.

Nova rota aprovada GET `/api/v1/settings`, somente ADMIN: objeto estritamente
permitido com `email_enabled`, `telegram_enabled`, `alert_cooldown_seconds`,
`alert_poll_interval_seconds`, `alert_test_cooldown_seconds`. Intervalos condicionais
podem ser null quando ambos os canais estiverem desabilitados; configuração ativa
inválida retorna 503 sanitizado. Sem despejar os.environ ou incluir host/endereço/senha.
Os valores descrevem configuração carregada pela API, não confirmam prontidão de
credenciais nem que um worker já reiniciou com esses valores. Sem endpoint de escrita.

## 7. P8 — Escopo de implementação, validação e aprovação

| Etapa | Entrega aprovada |
| --- | --- |
| 1 (concluída) | Documento de contratos, confirmado integralmente pelo usuário |
| 2 (concluída) | Cálculo operacional e marcador de contexto aprovado; testes/migration |
| 3 (concluída) | Três endpoints de dashboard e testes de agregações; 554 testes passaram |
| 4 (concluída) | API administrativa, regras compartilhadas com CLI e consulta segura /settings; 668 testes passaram |
| 5 (concluída) | Migration/fila de testes, worker, reconciliação e regressão integrada; 749 testes passaram |

As telas permanecem na Fase 8. Não renumerar fases anteriores nem marcar como
implementados os requisitos novos. A matriz abaixo orienta aceite, não relata testes:

- Estado: tabela de prioridade inteira, manutenção com falha, múltiplos dispositivos,
  ausência de evidência, reativação/reassociação, replay e datas fora de ordem.
- Dashboard: consistência de contadores, UNKNOWN separado, intervalos UTC nas
  fronteiras, zeros, filtro e limite de buckets, RBAC e banco indisponível.
- Destinatários: validação de entrada, identidade vinculada, inativação, canais
  legados, corrida com enqueue/reserva, ausência de credenciais em respostas/logs.
- Testes de envio: UUID concorrente, cooldown, snapshot, autorização na reserva,
  rollback, crash antes/depois do envio, fila justa, provider aceitou versus entrega
  incerta, reconciliação sem reenvio e proteção do histórico real.
- Executar testes, build relevante, healthchecks e migrations em schemas isolados;
  migration no banco local só na etapa autorizada, preservando volume e dados.
  Não enviar mensagens reais sem autorização específica do usuário.

P1–P8 foram confirmados integralmente. Mudanças posteriores nesse contrato
precisam ser identificadas e discutidas; não aplicar decisões diferentes silenciosamente.
Dashboard implementado na etapa 3. Administração web e /settings implementados
na etapa 4, descritos em [alert-administration.md](alert-administration.md).
Fila de testes, proteção de identidade e processamento implementados na etapa 5,
descritos em [alert-tests.md](alert-tests.md). Migration 0005 aplicada preservando
os dados anteriores. Evidências e limites em [testing.md](testing.md); nenhum
envio real nesta entrega. Frontend não iniciado.
