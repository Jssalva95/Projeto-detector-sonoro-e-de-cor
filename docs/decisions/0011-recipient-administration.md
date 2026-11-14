# 0011 — Identidade do destinatário e tentativas concorrentes

Data: 2026-11-14. Status: implementa contrato P4 aprovado, etapa 4 de preparação
do frontend. Sem alteração de schema ou do contrato de entrega da Fase 6.

alerts não guarda snapshot do destino. Permitir editar destino/canal depois de
criar uma tentativa mudaria o significado do histórico e poderia redirecionar
um envio pendente. API e CLI passam a compartilhar regras de destinatário; a
identidade torna-se imutável depois de qualquer tentativa, inclusive FAILED.
Nome e atividade continuam editáveis. IDs diferentes continuam independentes.

Uma consulta prévia sem bloqueio não protege contra enqueue concorrente. Por isso:

1. Edição/ativação/desativação adquire FOR UPDATE no destinatário e recarrega o
   estado ORM com populate_existing; depois consulta tentativas e valida mudanças.
2. Enqueue mantém a ordem existente dispositivo → máquina, seleciona destinatários
   ativos/habilitados por ID crescente com FOR UPDATE, recarrega os objetos e
   revalida elegibilidade. A referência de tempo é obtida após os bloqueios.
3. Reserva mantém FOR UPDATE SKIP LOCKED da tentativa e bloqueia o destinatário
   antes de revalidar atividade/canal e capturar destino. Commit antecede I/O.
4. Retry manual mantém evento → tentativa e então bloqueia/revalida destinatário.
5. A edição que já possui o lock do destinatário **não** adquire lock de tentativa
   ou evento: a consulta de existência é uma leitura normal. Evita inverter as
   ordens anteriores. Finalização da entrega bloqueia somente a tentativa.

Sob READ COMMITTED, uma edição que aguardou enqueue enxerga a tentativa já
confirmada na consulta seguinte e recusa a troca. Se edição ganhar primeiro,
enqueue/reserva reavaliam os valores confirmados após aguardar. Testes cobrem
objetos ORM carregados antes da espera para detectar uso acidental de cache.

Desativar após commit da reserva não cancela o envio já capturado. Não há locks
durante transporte externo nem mudança na política de ausência de retry automático.
As novas consultas administrativas usam contagem e página na mesma instrução SQL.

O protocolo exige os writers da aplicação atualizados; não protege edições diretas
feitas por administrador SQL ignorando os serviços. Instâncias antigas devem ser
substituídas antes de usar a edição web de identidade. O bloqueio compartilhado
pode serializar filas de máquinas distintas para o mesmo destinatário; não há
promessa de desempenho sob carga nesta etapa.

Quando alert_test_attempts for criada na etapa 5, o guard de identidade e os novos
writers deverão incluir essa tabela e seguir a mesma coordenação. Não antecipar
sua migration, endpoints ou envio aqui.
