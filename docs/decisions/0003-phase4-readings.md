# Contratos da Fase 4

Status: aprovado pelo usuário no prompt adaptado da Fase 4.

## Contexto

O mestre exige POST/GET de readings, consulta por ID, filtros e paginação, mas
não detalha autenticação, respostas, limites ou comportamento após reassociação.
A Fase 1 já definiu toda a estrutura persistente necessária.

## Decisão

- POST com X-API-Key existente; GETs com access JWT de usuário ativo e role atual
  ADMIN, OPERATOR ou VIEWER. Reutilizar dependências de segurança existentes.
- UUID obrigatório do cliente; duplicidade retorna 409 sem sobrescrever leitura.
- Máquina/dispositivo inexistente: 404; inativo: 403; associação incompatível: 409.
- Validar associação atual sob o mesmo lock da atualização do dispositivo. Não
  inferir associação histórica para novas leituras atrasadas. Histórico persistido
  permanece na máquina original após reassociação.
- POST retorna 201; consultas 200; leitura ausente 404. Lista é array, sem total.
- Datas com fuso, em UTC, inclusivas; intervalo invertido 422. Filtros por AND.
- Limit padrão 50, faixa 1..200; offset padrão 0 e não negativo. Ordenação por
  timestamp DESC e id DESC. Paginação inválida retorna 422, sem ajuste silencioso.
- Nenhuma alteração estrutural no banco, de estado, heartbeat, eventos ou alertas.

## Consequências

A chave compartilhada permanece sem identidade criptográfica individual.
Paginação offset pode deslocar páginas quando há novas inserções. A rejeição de
leituras para a associação anterior é intencional; não há tabela de associações
históricas. Índices existentes e migration 0002 são suficientes para esta fase.

Contrato completo: [readings.md](../readings.md).

## Correção aprovada após auditoria

A auditoria encontrou HTTP 500 para amplitude não finita e HTTP 503 para offset
acima de BIGINT. O usuário aprovou rejeitar essas entradas com 422: amplitude
de leitura deve ser finita e offset deve estar entre 0 e 9223372036854775807.
Overflow de número JSON também é rejeitado sem ecoar infinito na resposta de erro.
Amplitude bruta finita, inclusive negativa ou acima de 1, permanece aceita.
Sem alteração de schema PostgreSQL, dependências ou contratos de eventos.
