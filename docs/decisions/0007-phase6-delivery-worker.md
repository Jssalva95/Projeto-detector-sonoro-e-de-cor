# 0007 — Reserva durável antes do envio

Status: implementado no escopo autorizado da Fase 6.3.

## Decisão

Worker separado, mesma imagem do backend, ativado explicitamente pelo perfil
Compose `alerts`. Consulta uma tentativa PENDING não iniciada por vez, com
FOR UPDATE SKIP LOCKED. A migration 0003 acrescenta attempt_started_at nullable;
reserva é confirmada antes de I/O externo. Resultado é persistido depois, sem
transação aberta durante o envio.

## Consequências

Tentativas iniciadas nunca voltam automaticamente à fila. Queda entre reserva e
envio pode exigir ação manual mesmo quando nada foi enviado; queda entre envio
e persistência do resultado pode esconder aceitação externa. Não há exactly-once
nem retry automático de resultados incertos. Erros operacionais param o worker.

CLI administrativa permite cadastro/ativação de destinatários e novas tentativas
explícitas com reconhecimento do risco de duplicidade. Reconciliação de PENDING
iniciado exige declaração de que todos os workers estão parados. Preserva
histórico e bloqueia reexecução do mesmo pedido após existir tentativa mais nova.

Template deriva dados do evento e metadados da máquina/destinatário na reserva,
sem campos adicionais de snapshot. Inativações posteriores não cancelam envios
em andamento. Polling configurado pelo usuário em 10 segundos, sem default.

Limites, comandos e operação: [alert-worker.md](../alert-worker.md).
