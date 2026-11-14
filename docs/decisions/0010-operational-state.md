# 0010 — Estado operacional separado do cadastro

Data: 2026-11-14. Status: contrato aprovado, implementação da etapa 2 de preparação
do frontend. Fonte: [P1 e P2](../pre-frontend-contracts.md).

Preservar machines.status como cadastro. Consultar fault_active por última
transição da máquina por Event.id, mantendo o ciclo já usado pela fila. Calcular
disponibilidade a partir dos dispositivos ativos atuais, sem timeout de heartbeat.
Manutenção prevalece, seguida de falha, offline e recuperação com dispositivo online;
evidência insuficiente resulta em operacional null, não em NORMAL presumido.

O repositório lê máquinas, dispositivos e últimas evidências em uma única consulta
PostgreSQL com joins laterais. O serviço monta schemas tipados, sem gravar estado,
alterar histórico ou gerar alertas. Não há consulta lazy adicional por máquina.
Não existe endpoint novo nesta etapa; a etapa 3 consumirá esse serviço.

A migration 0004 adiciona devices.status_event_id_floor BIGINT NOT NULL DEFAULT 0,
CHECK >= 0, sem FK. O 0 estrutural representa ausência de evento, não configuração
operacional. Bloqueios de tabela protegem o preenchimento por max(Event.id) de cada
dispositivo; depois de migrar, evidência anterior não comprova conectividade atual.
Dados e estados cadastrados permanecem preservados.

Reassociação e reativação atualizam o marcador sob o bloqueio do dispositivo também
usado pela ingestão. Leituras com FOR UPDATE recarregam o objeto ORM, para evitar
usar estado em cache anterior à espera do lock. Só eventos novos acima do marcador
e com machine_id correspondente podem indicar conectividade. Falhas por máquina
continuam independentes desse marcador e preservam seu histórico.

O campo não entra em DeviceCreate/DeviceUpdate/DeviceRead. Datas dos produtores
podem estar atrasadas: o cálculo representa última evidência persistida, não prova
de disponibilidade física nem cronologia dos sensores. ONLINE sozinho não implica
NORMAL. Sem migração reversa automática: remover/recriar o marcador perde informação
de contexto e não é procedimento de recuperação em produção.
