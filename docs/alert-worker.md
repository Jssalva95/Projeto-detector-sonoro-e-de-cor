# Fase 6.3 — processamento e administração da fila

O worker é separado da API, mas usa a mesma imagem Docker. Consome a fila da
[Fase 6.2](alert-queue.md) usando os [providers da Fase 6.1](providers.md).
Não há broker, scheduler externo, novas dependências, WhatsApp, SMS ou WebSocket.

## Migration e estados

`0003_alert_attempts` acrescenta apenas `alerts.attempt_started_at TIMESTAMPTZ NULL`.
Não altera PKs, FKs, índices, constraints ou registros anteriores. O campo também
é exposto no schema interno AlertRead, sem nova rota HTTP.

| Estado | Significado | Ação automática |
| --- | --- | --- |
| PENDING, attempt_started_at NULL | Aguardando primeira tentativa deste registro | Elegível se canal habilitado |
| PENDING, attempt_started_at preenchido | Em processamento ou resultado ainda desconhecido | Nunca reservar novamente |
| SENT | Provider confirmou aceitação | Nenhum reenvio |
| FAILED | Rejeição, entrada inelegível ou resultado incerto registrado | Nenhum retry automático |

Cada iteração reserva no máximo um registro, por ID, usando `FOR UPDATE SKIP
LOCKED`. Confirma `attempt_started_at` em uma transação curta **antes** do envio.
O envio ocorre sem manter conexão/transação de banco aberta. Outra transação
registra SENT/sent_at ou FAILED/error_message, preservando o marcador da tentativa.

A API continua criando filas sem esperar pelo envio. Dois workers não reservam
o mesmo registro. Não há garantia de exactly-once no serviço externo: se o
processo morrer após a reserva, inclusive antes de chamar o provider, o registro
fica para análise manual. Se morrer após aceitação e antes de registrar SENT,
também não haverá reenvio automático. Prioriza-se evitar mensagens duplicadas.

Erros do provider são persistidos somente se pertencem à lista de códigos
sanitizados; erros inesperados viram `delivery_unconfirmed`. Nenhuma exceção
remota, URL com token, senha, mensagem completa ou destino aparece nos logs.
Os [códigos SMTP](providers.md) distinguem conexão, TLS, negociação, autenticação,
rejeição de envio e resultado incerto. A primeira rejeição de autenticação é
preservada se a negociação terminar em falha. Todos continuam FAILED, com
`sent_at` vazio e sem retry automático; não há novos estados ou migrations.
Erros de banco/commit interrompem o processo com código de saída 1, sem restart
automático configurado no Compose. Após resolver a causa, reiniciar não retoma
tentativas que já possuem marcador.

## Elegibilidade e mensagem

Na reserva, o worker verifica novamente destinatário ativo, canal compatível e
evento FAULT_CONFIRMED. Inelegíveis são marcados FAILED com código fixo, sem envio.
Canais desabilitados ficam na fila sem marcador. Campos de máquina são lidos
pela associação histórica `event.machine_id`, nunca pela associação atual do
dispositivo. Os metadados da máquina e o destino são os existentes na reserva;
não há snapshot histórico adicional no banco. Mudanças posteriores não cancelam
um envio já reservado.

O template inclui máquina, número de série, bloco/corredor, UUID, horário UTC,
cor, presença de som e amplitude bruta. Campos ausentes aparecem como
"Não informado"; não se inventa vermelho/som detectado nem converte amplitude
para dB. Não se inclui o texto livre do evento. Mensagens Telegram acima do
limite do provider falham sem truncamento/splitting silencioso.

## Configuração e execução

`ALERT_POLL_INTERVAL_SECONDS` é obrigatório, positivo e finito, sem default.
O usuário escolheu **10 segundos** no `.env` local. Ele controla somente a espera
quando não existe trabalho; fila com itens elegíveis é drenada sem essa espera.
Timeouts de transporte e `ALERT_COOLDOWN_SECONDS=300` continuam independentes.
Configuração é carregada ao iniciar; mudanças exigem reinício/recriação do processo.

Preparação, na raiz do repositório:

```powershell
docker compose config --quiet
docker compose build backend
docker compose run --rm --no-deps backend python -m alembic upgrade head
docker compose up -d --wait backend
```

Teste de inicialização **sem envio**, mesmo se houver filas reais:

```powershell
docker compose run --rm --no-deps -e TELEGRAM_ENABLED=false -e EMAIL_ENABLED=false alert-worker python -m app.alerts.worker --once
```

Para operação real, configurar credenciais/timeouts dos providers, destinatários
e canais habilitados, e então ativar explicitamente:

```powershell
docker compose --profile alerts up -d alert-worker
docker compose ps alert-worker
docker compose logs --tail 20 alert-worker
docker compose stop alert-worker
```

Ativar o worker com canais habilitados pode enviar os itens já pendentes. Não
executar esse passo como simples smoke test. `--once` também envia, se houver um
item elegível e canais habilitados. O worker não expõe porta HTTP nem possui
healthcheck que prometa validade das credenciais externas: confira o processo e
o log `alert_worker_ready`. API e PostgreSQL mantêm seus healthchecks.

SIGINT/SIGTERM solicitam parada após a tentativa corrente. Encerramento forçado
pode deixar resultado incerto. Cancelar uma coroutine SMTP não cancela sua thread;
não inferir falha de envio apenas porque houve interrupção do processo.

Entre itens, o worker cede controle ao loop assíncrono para processar pedidos de
parada mesmo quando a fila permanece ocupada e o item termina sem I/O assíncrono
(por exemplo, destinatário inativo). Essa passagem não adiciona intervalo de
polling nem cancela a tentativa corrente. O próximo item permanece sem reserva.

## Administração manual

A CLI exige acesso administrativo ao host/container e banco; não é uma API
pública, não cria autenticação adicional nem executa seeds. Substitua os valores
em maiúsculas pelos dados reais antes de executar:

```powershell
docker compose exec -T backend python -m app.alerts.admin add-recipient --name "NOME_REAL" --channel EMAIL --destination "EMAIL_REAL"
docker compose exec -T backend python -m app.alerts.admin list-recipients --limit 20
docker compose exec -T backend python -m app.alerts.admin list-alerts --limit 20
```

Também existem `activate-recipient ID` e `deactivate-recipient ID`. A criação
valida Telegram/e-mail; não altera automaticamente um destinatário existente.
IDs distintos são independentes, inclusive se o endereço for igual. As listagens
não imprimem destinos, texto da mensagem ou detalhes brutos de falhas. Alterar
destino/canal não é exposto: cadastre o correto e desative o anterior.

Para nova tentativa de um FAILED, após análise operacional:

```powershell
docker compose exec -T backend python -m app.alerts.admin retry ID --accept-duplicate-risk
```

Cria **outro** registro PENDING, mantendo o registro anterior. É uma exceção manual
ao ciclo/cooldown automático; usa mesmo evento/destinatário/canal. Só a tentativa
mais recente dessa combinação pode originar outra. Repetir o mesmo comando não
cria outro registro enquanto existir tentativa mais nova. SENT e PENDING ainda
não iniciado não podem ser reenviados por esse comando.

Para um PENDING com marcador, primeiro parar **todos** os workers (inclusive
processos locais), conferir o resultado no provider e assumir explicitamente
o risco de duplicidade. Só então usar:

```powershell
docker compose exec -T backend python -m app.alerts.admin retry ID --accept-duplicate-risk --workers-stopped
```

`--workers-stopped` é declaração do operador, não detecção automática de processos.
O comando marca o original FAILED/delivery_unconfirmed e cria a nova tentativa
atomicamente. Nunca usar enquanto algum envio daquele registro puder continuar.
Não há reclassificação automática de tentativas antigas por timeout/idade.

## Validação e limites

`test_alert_delivery.py` usa PostgreSQL real em schemas privados e providers
simulados, cobrindo transações independentes, falhas antes/depois do envio,
cancelamento, concorrência, SKIP LOCKED, configuração, template, CLI e migration.
Não comprova entrega real, handshake TLS externo ou desempenho sob carga.

Downgrade da migration foi testado somente em schema isolado. Em produção,
remover os marcadores e reaplicar a migration pode tornar tentativas incertas
elegíveis novamente; não fazer downgrade como procedimento de recuperação.

Referências de implementação: [bloqueios de linha no PostgreSQL 17](https://www.postgresql.org/docs/17/sql-select.html#SQL-FOR-UPDATE-SHARE)
e [perfis opcionais do Docker Compose](https://docs.docker.com/compose/how-tos/profiles/).
