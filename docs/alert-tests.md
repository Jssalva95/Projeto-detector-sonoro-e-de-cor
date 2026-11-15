# Testes de envio — preparação do frontend, etapa 5

Implementa P5/P6 de [pre-frontend-contracts.md](pre-frontend-contracts.md).
Não cria eventos, alertas reais, sensores ou destinatários. Todas as rotas exigem
ADMIN ativo com JWT access e role atual no banco.

## API

| Rota | Resultado |
| --- | --- |
| POST /api/v1/alert-recipients/{id}/test | Corpo somente `{"uuid":"UUID_GERADO_PELO_CLIENTE"}`; 202 persistido, 200 replay |
| GET /api/v1/alert-tests/{id} | Tentativa ou 404 |
| GET /api/v1/alert-tests | Filtros recipient_id/status, limit=50 (máximo 200), offset>=0; total/limit/offset/items |

Listagem por id decrescente, total/itens no mesmo snapshot. Resposta: id, uuid,
recipient_id, requested_by, channel, status, created_at, attempt_started_at,
sent_at e error_message. O snapshot destination não é exposto. Códigos legados
desconhecidos viram delivery_unconfirmed apenas na resposta.

Mesmo UUID/solicitante/destinatário retorna a tentativa existente, mesmo FAILED
ou com destinatário depois desativado. Replay antecede elegibilidade,
configuração e cooldown; o solicitante ainda precisa ser ADMIN ativo.
UUID com outro solicitante/destinatário retorna 409 sem expor o registro.
Após falha da resposta HTTP, repetir o mesmo UUID, sem gerar outro automaticamente.

Novo pedido exige destinatário ativo EMAIL/TELEGRAM, canal habilitado/configurado
e nenhum PENDING desse destinatário. Inelegível/em andamento: 409; configuração
inválida: 503; entrada inválida: 422; destinatário inexistente: 404.
Validar configuração não abre conexão externa.

ALERT_TEST_COOLDOWN_SECONDS é obrigatório, finito e não negativo, sem default;
local aprovado: 300s. Usa o horário do PostgreSQL e a última criação persistida
por destinatário, inclusive FAILED/SENT. Antecipação retorna 429 e Retry-After
arredondado para cima. Replay não renova a espera. Zero explícito remove a espera,
mas mantém a proibição de dois PENDING. Não é rate limit global.

## Persistência e envio

Migration 0005_alert_test_attempts cria tabela própria; tabelas anteriores
permanecem intactas. BIGINT identity, UUID único, timestamps UTC, FKs RESTRICT
para users/alert_recipients, CHECKs de canal/status/resultado/datas e UNIQUE
parcial de destinatário PENDING. Histórico de teste também impede mudar
destination/channel do destinatário; nome/atividade continuam editáveis.

O worker existente alterna alertas reais e testes, uma tentativa por vez.
Fila vazia não impede a outra. Reutiliza providers/timeouts e polling existentes.
Assunto fixo de e-mail: **Machine Monitor — teste de envio**. O corpo saúda,
identifica o teste/UUID e informa que não é falha de máquina. Telegram usa o mesmo
corpo. O assunto dos alertas reais permanece intacto.

Na reserva, revalidar solicitante ADMIN ativo e destinatário ativo com identidade
igual ao snapshot. Falhas: requester_inactive, requester_not_admin,
recipient_inactive ou recipient_identity_changed. Canal desabilitado permanece
PENDING sem reserva. Confirmar marcador antes de I/O externo; desativação depois
da reserva não cancela envio iniciado.

SENT é aceitação pelo provider, não comprovação na caixa de entrada. SMTP mantém
a primeira rejeição de autenticação classificada. Falhas incertas usam
delivery_unconfirmed; não há retry automático. Queda/cancelamento/falha de commit
de resultado mantém PENDING iniciado, mesmo quando o envio pode não ter começado.
Esse registro bloqueia novo teste do destinatário. Sem garantia exactly-once.

## Reconciliação manual

Parar todos os workers, inclusive locais, e verificar o resultado externo.
Só então usar o ID interno da tentativa de teste:

```powershell
docker compose exec -T backend python -m app.alerts.admin reconcile-test ID --workers-stopped
```

A flag é declaração do operador, não detecção de processos. Só PENDING com
marcador pode ser encerrado. Grava FAILED/delivery_unconfirmed, preservando
UUID/datas/snapshot; não envia nem cria substituta. Repetição, SENT, FAILED e
PENDING sem marcador são recusados. Novo teste exige novo UUID e cooldown.
Não confundir o ID com Alert.id: são tabelas independentes.

Ativar o perfil alerts pode enviar itens das duas filas. Testes automatizados
usam schemas privados e providers simulados. Implantação em [deployment.md](deployment.md).
