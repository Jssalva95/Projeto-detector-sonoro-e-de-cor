# 0006 — Fila transacional e serialização por máquina

Status: implementado na Fase 6.2 autorizada pelo usuário.

## Decisão

Integrar enqueue ao serviço de ingestão, dentro do savepoint e transação
existentes. Bloquear a máquina após o dispositivo e antes da inserção para
serializar ciclos inclusive entre dispositivos distintos. Consultar a última
transição persistida por ID, sem inferir status de máquina ou reordenar datas.

Reutilizar `events`, `alert_recipients` e `alerts`, com índices existentes.
Registrar PENDING somente no primeiro FAULT_CONFIRMED do ciclo para destinatários
ativos de canais habilitados, sujeito ao cooldown por máquina/destinatário/canal.
Não adicionar unicidade que impeça tentativas futuras aprovadas na modelagem.

## Consequências

Falhas de enqueue revertem evento e alertas. Configuração inválida retorna 503
sanitizado. Replays e ciclos já ativos não geram fila retroativa. O cooldown conta
criação de alertas de qualquer status, pelo relógio do banco após o bloqueio;
valor local de 300 segundos definido explicitamente pelo usuário, sem default.

Não há envio, worker ou retry. Um ciclo suprimido não é agendado para mais tarde,
e uma falha persistente não gera lembretes periódicos. A serialização reduz o
paralelismo por máquina, preservando paralelismo entre máquinas distintas.

Contrato detalhado: [alert-queue.md](../alert-queue.md).
