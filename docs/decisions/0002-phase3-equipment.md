# Contratos da Fase 3

Status: aprovado pelo usuário.

## Contexto

O mestre exige CRUD e heartbeat, mas o exemplo usa identificadores textuais com
nomes que poderiam ser confundidos com as PKs BIGINT aprovadas. A autenticação da
Fase 2 atende usuários; a chave para dispositivos estava apenas declarada.

## Decisão

- CRUD com POST/GET e GET/PATCH/DELETE por ID interno. PATCH segue a tarefa explícita
  aprovada para a Fase 3, em lugar do PUT do exemplo do documento mestre.
- ADMIN escreve; ADMIN, OPERATOR e VIEWER leem máquinas e dispositivos.
- DELETE físico somente sem referências, com 409 para restrição; desativação via PATCH.
- Heartbeat com device_uid/serial_number e X-API-Key usando DEVICE_API_KEY.
- Dispositivo inativo retorna 403; associação incompatível retorna 409.
- Firmware omitido é preservado; horário last_seen_at vem do servidor em UTC.
- ONLINE e uptime_seconds opcionais são validados sem persistência ou efeitos de estado.
- Resposta DeviceRead; não criar cadastros implicitamente nem alterar schema.

## Consequências

Não há identidade/chave individual por dispositivo nem detecção de offline nesta
fase. Reassociação preserva o histórico existente. Nenhuma funcionalidade de
telemetria, eventos, alertas, WebSocket, frontend ou hardware foi antecipada.

Contrato operacional: [equipment.md](../equipment.md).
