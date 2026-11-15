# Administração de alertas — preparação do frontend, etapa 4

Implementa [P4 e a consulta de P7](pre-frontend-contracts.md). Todas as rotas abaixo
exigem **ADMIN ativo com JWT access**. Ausência de credencial, refresh, chave de
dispositivo, token expirado ou usuário inativo retornam 401; OPERATOR/VIEWER,
403. A role é consultada no banco em cada requisição. Não há cadastro de usuários.

## Destinatários

| Método e rota | Comportamento |
| --- | --- |
| GET /api/v1/alert-recipients | Filtros channel/is_active; total/limit/offset/items; id crescente |
| GET /api/v1/alert-recipients/{id} | Destinatário ou 404 |
| POST /api/v1/alert-recipients | name, channel EMAIL/TELEGRAM, destination, is_active opcional true; 201 |
| PATCH /api/v1/alert-recipients/{id} | Campos parciais, null recusado; 200, 404, 409 ou 422 |

Paginação padrão 50, máximo 200, offset não negativo até BIGINT máximo. Total é
calculado após filtros, antes da paginação, no mesmo snapshot dos itens; offset
além do fim mantém o total e retorna lista vazia. Filtros sem correspondência
também retornam lista vazia. A resposta de destinatário contém somente id, name,
channel, destination, is_active, created_at e updated_at.

Nome não pode ser vazio ou conter NUL/CR/LF. E-mail e Telegram reutilizam a
validação da CLI: endereço simples ASCII, chat ID numérico ou identificador
Telegram @nome. Isso valida formato; não confirma que o endereço existe.
Destinatários com o mesmo endereço continuam sendo IDs independentes.

Qualquer tentativa em alerts ou alert_test_attempts bloqueia mudança de canal/destino com 409,
independentemente de estar PENDING, SENT ou FAILED. Repetir o mesmo valor é
permitido, assim como mudar nome ou atividade. Antes de existir tentativa,
canal/destino podem ser corrigidos. Para outra identidade com histórico,
cadastrar novo destinatário e desativar o anterior. Não existe DELETE.

Registros SMS/WHATSAPP legados podem ser consultados/desativados, sem implementar
providers, criação ou ativação desses canais. A CLI compartilha criação,
validação, ativação e desativação com a API; o retry continua sendo exclusivamente
manual na CLI. Nenhuma rota de retry/reconciliação foi acrescentada.

A etapa 5 acrescenta a tabela de testes e sua proteção de identidade.
Rotas e execução independente estão em [alert-tests.md](alert-tests.md).

## Tentativas reais

| Método e rota | Comportamento |
| --- | --- |
| GET /api/v1/alerts | Filtros event_id, recipient_id, machine_id, channel, status; total/limit/offset/items; id decrescente |
| GET /api/v1/alerts/{id} | Tentativa ou 404 |

Mesmos limites de paginação. machine_id é o da ocorrência histórica em Event,
não o vínculo atual do dispositivo. Não há filtros implícitos por destinatário
ativo ou canal habilitado: histórico desativado/legado continua consultável.

A resposta usa AlertRead, incluindo attempt_started_at. error_message aceita
somente os códigos já sanitizados dos providers e da reserva; conteúdo legado
desconhecido vira `delivery_unconfirmed` **na resposta**, preservando o banco.
Destinos não são acrescentados à resposta de tentativa. SENT significa aceitação
pelo provider, não confirmação de entrega na caixa do destinatário. PENDING com
marcador não é uma tentativa livre para reenviar.

## Consulta segura de configuração

GET `/api/v1/settings`, sem endpoint de escrita. Lista exata dos campos:

- email_enabled;
- telegram_enabled;
- alert_cooldown_seconds;
- alert_poll_interval_seconds;
- alert_test_cooldown_seconds.

Com ambos os canais desabilitados, intervalos retornam null e configurações de
providers desabilitados não são exigidas. Com algum canal ativo, configurações
locais dos providers habilitados e intervalos são validados; erro retorna 503
sanitizado. Não ocorre DNS, conexão, autenticação ou envio para serviços externos.
Host, remetente, credenciais, tokens e variáveis arbitrárias nunca são serializados.

`ALERT_TEST_COOLDOWN_SECONDS` foi acrescentada ao Compose e .env.example. Valor
local aprovado: 300s, sem default no código. Assim como cooldown real, aceita
número finito não negativo; zero explicitamente desabilita a espera.
A etapa 5 aplica esse valor à fila de testes; /settings também o expõe.
O polling continua positivo; configurações operacionais existentes não foram alteradas.

Os valores descrevem o ambiente da API, não provam prontidão de credenciais nem
que outro processo worker carregou os mesmos valores. Mudanças no .env exigem
recriar o serviço para atualizar seu ambiente.

## Bloqueios e privacidade

[ADR 0011](decisions/0011-recipient-administration.md) documenta a ordem dos
bloqueios. API, CLI, enqueue, reserva e retry coordenam-se no destinatário e
revalidam o registro após a espera. Desativação não cancela entrega já reservada.
Os testes usam transações distintas e confirmam bloqueio real no PostgreSQL.

Respostas administrativas bem-sucedidas usam Cache-Control: no-store. Erros de
entrada não repetem payload/destino; falhas de banco retornam 503, sem erro bruto
ou falso sucesso vazio. Não há log de payload ou destino nessas operações.

Sem novas dependências ou migrations. A implantação deve atualizar API, CLI e
workers para a mesma versão; uma instância antiga não participa desse protocolo
de bloqueios. Não iniciar workers com filas reais para testar esta etapa.
Veja [deployment.md](deployment.md) e [testing.md](testing.md).
