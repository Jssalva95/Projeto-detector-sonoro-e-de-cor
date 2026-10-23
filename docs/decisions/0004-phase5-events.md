# Contratos da Fase 5

Status: aprovado pelo usuário antes da implementação.

## Decisão

Implementar apenas criação/consulta de eventos, severidade fornecida pelo produtor,
UUID idempotente e reconhecimento. Reutilizar banco e autenticação existentes.

- Ingestão X-API-Key; consultas ADMIN/OPERATOR/VIEWER com access JWT; acknowledge
  ADMIN/OPERATOR com access JWT e usuário ativo/role atual no banco.
- Entrada pública separada do EventCreate interno para impedir escrita dos campos
  de reconhecimento e demais metadados do servidor.
- UUID novo 201; mesmo UUID e ocorrência normalizada idêntica 200; divergência 409.
  Não comparar metadados de reconhecimento. Não alterar ocorrência em retry.
- Dispositivo ativo obrigatório inclusive em retries. Associação atual exigida
  para evento novo; retry idêntico após reassociação retorna o histórico existente.
- Acknowledge sem corpo; primeiro responsável/horário confirmado é preservado,
  inclusive sob concorrência. Repetições retornam 200. Não implica recuperação.
- Filtros conforme mestre, datas inclusivas sobre started_at, UTC e paginação
  50 por padrão/máximo 200; offset até máximo BIGINT. Array sem total e ordem
  started_at DESC, id DESC.
- Nenhuma inferência de severidade ou Machine.status, envio de alerta ou detecção.

## Consequências

Sem migration/dependência nova. ON CONFLICT na constraint UUID e bloqueio de linha
no reconhecimento protegem a concorrência; dados de ocorrência são imutáveis
pela API nesta fase. A tabela de eventos não é uma máquina de estados nem um
histórico completo de associações. A autorização de dispositivo continua baseada
na chave compartilhada existente.

Contrato operacional: [events.md](../events.md).
