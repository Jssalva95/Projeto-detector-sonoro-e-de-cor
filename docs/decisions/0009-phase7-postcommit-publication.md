# 0009 — Publicação WebSocket após commit — Fase 7.2

Status: implementação do contrato aprovado para publicação transitória em processo único.

A rota POST de eventos prepara um snapshot imutável apenas para ocorrência nova
dos quatro tipos críticos definidos na especificação. `get_session` publica após
a saída bem-sucedida de `session_scope`, que confirma a transação raiz. Não são
usados hooks `after_commit` globais, evitando confundir commit de savepoint com
commit principal. A publicação fica explicitamente restrita à ingestão HTTP atual.

O gerenciador usa o loop ASGI e filas limitadas por conexão. O thread da requisição
agenda a entrega sem aguardar o socket. Um único consumidor por cliente revalida
o usuário antes de enviar; as tarefas de envio/recepção são canceladas ao encerrar.
Fila cheia encerra o cliente com 1013. Demais clientes e persistência são preservados.

O usuário aprovou `WS_CLIENT_QUEUE_SIZE=100` para o `.env` local. Configuração
obrigatória sem default; timeout de envio reutiliza os 5 segundos já aprovados.
Não há alteração de schema, contratos REST ou lógica de alertas.

Limitações aceitas: sem outbox durável, broker, replay ou ordenação global entre
requisições concorrentes. Falha após commit pode perder a notificação; o cliente
consulta REST após reconectar. Não existem detecção automática de offline ou
transmissão de COLOR_RED/ALARM_SOUND. A 7.3 permanece uma tarefa separada.
