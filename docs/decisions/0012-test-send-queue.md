# ADR 0012 — Fila independente de testes de envio

Status: implementa P5/P6 aprovados. Data: 2026-11-14.

## Decisão

Persistir em alert_test_attempts, sem Event/Alert real, usando a migration aditiva
0005 e os campos/constraints aprovados. Nenhum novo provider, processo ou broker.
A API apenas grava; o worker alterna as duas filas, no máximo uma tentativa por
iteração. Fila preferida vazia permite consultar a outra; polling só ocorre se
nenhuma tiver trabalho elegível.

## Concorrência

Criação: lock consultivo transacional derivado do UUID (namespace alert-test),
usuário FOR SHARE e destinatário FOR UPDATE, nessa ordem. O lock UUID abrange
destinatários distintos; colisões de hash apenas serializam pedidos independentes.
UNIQUE(uuid) permanece a garantia estrutural. Reconsultar usuário/UUID após lock.

Sob lock do destinatário, verificar PENDING e cooldown com relógio do banco.
O mesmo lock coordena editores e writers reais; UNIQUE parcial de destinatário
PENDING protege também contra writers que contornem o serviço.

Reserva: tentativa FOR UPDATE SKIP LOCKED, usuário FOR SHARE, destinatário
FOR UPDATE. Recarregar elegibilidade, persistir marcador e confirmar antes de I/O.
Editor não bloqueia tentativas: consulta histórico sob lock do destinatário.
Reconciliação bloqueia só a tentativa. Não inverter essa ordem de aquisição.

## Consequências

Transporte reutiliza códigos sanitizados; cancelamento/falha de commit de resultado
mantém reserva durável, ignorada após reinício. reconcile-test exige declaração de
workers parados e só encerra uma tentativa incerta, sem enviar/criar substituta.
Snapshot destination fica na persistência/transporte, fora de respostas/logs.
Histórico em qualquer fila congela identidade do destinatário.
SMTP de teste usa assunto fixo próprio, preservando send(message, destination).

Parar writers antigos durante implantação e atualizar API/CLI/worker juntos.
Não fazer downgrade operacional: descartaria histórico/reservas; esse caminho
é validado somente em schemas privados. Sem garantia exactly-once, rate limit
global ou comprovação de entrega externa.
