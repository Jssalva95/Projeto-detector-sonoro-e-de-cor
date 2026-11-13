# 0008 — Autenticação e contrato WebSocket da Fase 7.1

Status: aprovado pelo usuário e implementado somente para conexão/autenticação.

Endpoint `/api/v1/ws/events`; autenticação em primeira mensagem JSON com access
token, sem credenciais em URL. Origin obrigatório e verificado em lista explícita.
Consulta usuário ativo e role atual no banco; ADMIN/OPERATOR/VIEWER podem ler.
Expiração fecha conexão; refresh continua via REST, seguido de reconexão.

Mensagens usam IDs internos BIGINT coerentes com REST. O usuário confirmou
explicitamente essa interpretação para `machine_id`, em lugar do número de série
ilustrativo na seção 24 do PROJECT_MASTER_PROMPT. UUID identifica a ocorrência;
timestamps são UTC. Não há mudança de schema ou de contratos REST.

Configurações locais explicitamente aprovadas: autenticação 10s, envio 5s,
mensagem recebida 4096 bytes, origens http://localhost:5173 e
http://127.0.0.1:5173. Todas obrigatórias e sem default no código.

Um único processo da API, conforme execução atual. O entrypoint `app.server`
centraliza limites de transporte e proteção de logs no Docker e no Windows.
Dependência de transporte específica `websockets==17.4`; não troca frameworks.

Publicação pós-commit, broadcast e filas de saída pertencem à 7.2. A opção
aprovada é distribuição transitória em memória, sem broker ou replay; REST será
a fonte de atualização após reconexão. A Fase 7 completa ainda não está concluída.

Contrato operacional: [websocket.md](../websocket.md).
