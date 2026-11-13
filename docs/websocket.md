# Fases 7.1 e 7.2 — conexão e publicação pós-commit

Endpoint: `WS /api/v1/ws/events`, na mesma porta do backend. Conexões autenticadas
recebem os quatro tipos críticos criados por `POST /api/v1/events`, somente após
commit. Entrega transitória em memória; não existe replay ou frontend nesta etapa.

## Configuração obrigatória

Valores aprovados pelo usuário para o ambiente local, sem defaults no código:

```dotenv
WS_AUTH_TIMEOUT_SECONDS=10
WS_SEND_TIMEOUT_SECONDS=5
WS_MAX_MESSAGE_BYTES=4096
WS_CLIENT_QUEUE_SIZE=100
WS_ALLOWED_ORIGINS='["http://localhost:5173","http://127.0.0.1:5173"]'
```

Timeouts precisam ser positivos e finitos; tamanho é um inteiro positivo em bytes.
Origens são um array JSON não vazio de URLs http/https exatas, sem caminhos,
credenciais, query, fragmento ou wildcard. Não há derivação automática da porta.
Alterações de domínio/porta do frontend exigem atualizar essa lista explicitamente.
Não aceita Origin ausente, `null`, duplicado ou fora da lista, nem query na URL.
A checagem de Origin não substitui JWT: clientes não navegador podem forjar esse header.

O limite de bytes é aplicado à mensagem recebida no transporte e na aplicação,
antes de interpretar o JSON. O transporte mantém sua fila de entrada padrão do
Uvicorn. A fila de saída por cliente tem capacidade explícita em mensagens,
inteira e positiva, sem default. Compressão de mensagens está
desabilitada. Não foi criado heartbeat de aplicação; ping periódico do servidor
está desabilitado, mas o protocolo pode responder a ping do cliente.

## Protocolo de autenticação

O navegador abre a conexão e envia uma primeira mensagem de texto JSON:

```json
{"type":"authenticate","access_token":"ACCESS_TOKEN_OBTIDO_NO_LOGIN"}
```

O valor acima é um marcador documental, não uma credencial. O token não vai na URL,
em cookies nem em subprotocolos. Headers Authorization não substituem essa mensagem.
Não se aceita refresh token. Campos extras, mensagens binárias ou JSON inválido
são recusados, sem ecoar a entrada. Nenhum dado é transmitido antes da autenticação.

Após verificar assinatura, tipo, `sub`, `iat`, `exp`, existência/atividade do usuário
e role atual no PostgreSQL, o servidor responde:

```json
{"type":"authenticated","expires_at":"2026-11-07T12:05:00Z"}
```

Timestamp ilustrativo; o valor efetivo vem do JWT. Roles permitidas: ADMIN, OPERATOR
e VIEWER, as mesmas da consulta REST de eventos. Sessões de banco são curtas e
executadas fora do event loop; não ficam abertas enquanto o socket aguarda dados.
A conexão conserva apenas ID e expiração, sem token ou objeto ORM do usuário.

A primitiva de envio reconsulta atividade e role antes de cada mensagem. Uma
desativação posterior ao login bloqueia o próximo envio; não há consulta periódica
para expulsar imediatamente uma conexão ociosa. A expiração do JWT encerra a
conexão mesmo quando nenhum dado chega. Renovação permanece no endpoint REST
existente; depois é necessária uma nova conexão. Não há troca de token no socket.
Depois da autenticação, mensagens de aplicação recebidas são rejeitadas: canal
somente de leitura, sem comandos de atualização, filtros ou ACK nesta parte.

## Encerramentos

| Código | Motivo |
| --- | --- |
| HTTP 403 antes de aceitar | Origem/query recusada; configuração inválida também impede aceitar. |
| 4401 | JWT inválido/expirado, usuário inexistente ou inativo. |
| 4403 | Role não permitida. |
| 4408 | Prazo da autenticação inicial esgotado. |
| 1003 | Mensagem binária não suportada. |
| 1008 | Mensagem inválida ou comando não permitido. |
| 1009 | Mensagem recebida maior que o limite. |
| 1011 | Falha operacional, inclusive banco indisponível ou timeout de envio. |
| 1013 | Fila de saída cheia: reconectar e atualizar os dados por REST. |

Não são devolvidos detalhes brutos de exceções. Os logs de transporte configurados
pelo entrypoint removem queries do caminho WebSocket e descartam DEBUG/TRACE, que
podem conter frames e credenciais. Não habilite dumps de protocolo em produção.

## Contrato de evento

Schema imutável `EventNotification`, emitido para ocorrências novas confirmadas:

| Campo | Contrato |
| --- | --- |
| type | FAULT_CONFIRMED, FAULT_RECOVERED, DEVICE_OFFLINE ou DEVICE_ONLINE. |
| event_id | ID interno positivo BIGINT, JSON numérico, como na API REST. |
| uuid | UUID da ocorrência. |
| machine_id | ID interno positivo BIGINT, JSON numérico, como na API REST. |
| timestamp | `started_at` da ocorrência normalizado para UTC. |
| severity | INFO, WARNING ou CRITICAL, conforme persistido. |

O usuário aprovou ID interno para `machine_id`, esclarecendo o exemplo textual
`MACHINE-001` da seção 24 do documento mestre. Não significa número de série.
UUID permanece separado. Não foram adicionadas colunas ou migrations.

## Execução e limites

Docker usa `python -m app.server`, que valida a configuração antes de iniciar
Uvicorn com um único processo e aplica o limite de mensagens ao transporte.
No Windows, com as dependências instaladas e variáveis de ambiente exportadas,
use o mesmo comando dentro de `backend/`. Python não carrega `.env` automaticamente.
Evite iniciar diretamente `uvicorn app.main:app`: isso ignora os limites e filtros
de log definidos no entrypoint. A mudança não afeta o comando separado do worker.

`websockets==17.4` fornece o transporte que não existia na instalação mínima do
Uvicorn. FastAPI, Uvicorn e PostgreSQL mantêm as versões existentes. Compatibilidade
verificada por importação e por conexões reais em testes locais. Referências:
[Uvicorn WebSockets 0.34.2](https://github.com/encode/uvicorn/blob/0.34.2/uvicorn/protocols/websockets/websockets_impl.py)
e [websockets changelog](https://websockets.readthedocs.io/en/stable/project/changelog.html).

Em ambiente publicado, usar HTTPS/WSS com terminação TLS adequada. O Compose atual
é local, limitado a loopback. Não foi criado proxy/TLS público nesta subfase.

## Publicação e isolamento — 7.2

A rota de criação prepara um snapshot somente quando a ingestão retorna
`created=True`. A dependência `get_session` entrega esse snapshot ao gerenciador
depois que `session_scope` confirma a transação principal e fecha a sessão.
Flush e liberação do savepoint da ingestão não publicam. Rollback, falha de
persistência, erro de resposta antes do commit, UUID conflitante ou retransmissão
idêntica não geram notificação. Reconhecer um evento também não republica.
Chamadas diretas ao service fora desse fluxo HTTP não têm publicação automática.

O thread da requisição agenda a distribuição no loop ASGI sem aguardar rede.
Cada conexão possui uma fila limitada e um único consumidor; timeout de envio,
desconexão, expiração ou excesso de fila removem essa conexão e cancelam suas
tarefas. Um cliente lento não segura os outros nem a transação REST. Falhas de
publicação após commit são registradas sem detalhes sensíveis e não alteram o
resultado persistido ou repetem a criação de alertas.

`DEVICE_OFFLINE` e `DEVICE_ONLINE` são transmitidos apenas quando persistidos pela
ingestão existente. Não foi criada detecção automática de disponibilidade.
`COLOR_RED` e `ALARM_SOUND` não são transmitidos por este canal.

A entrega é transitória, em um único processo, sem broker, replay ou garantia
de entrega. Reinício, desconexão e a janela entre commit e publicação podem perder
notificações. Requisições concorrentes não têm garantia de ordem de chegada por ID.
Após reconectar, consultar REST para recompor o estado. A fila não substitui o
banco e não deve ser usada como histórico. Frontend permanece na Fase 8.

## Validação

```powershell
docker compose config --quiet
docker compose build backend
docker compose run --rm -T --no-deps backend python -m pytest -q tests/test_websocket.py tests/test_websocket_transport.py tests/test_websocket_publication.py
docker compose run --rm -T --no-deps backend python -m pytest -q
```

Testes usam JWTs fictícios e schemas PostgreSQL isolados. Os testes de transporte
iniciam um Uvicorn temporário em porta livre local, incluindo origem, autenticação,
expiração, desconexão, tamanho de mensagem e proteção dos logs. Não enviam alertas
externos, não usam credenciais de usuários reais e não dependem de hardware.
