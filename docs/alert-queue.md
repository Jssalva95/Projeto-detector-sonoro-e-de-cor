# Fase 6.2 — fila transacional de alertas

Esta etapa cria registros `alerts` com status `PENDING`. Não envia mensagens,
não instancia providers, não inicia worker e não implementa retries, CLI de
destinatários ou novos endpoints. Reutiliza o schema da migration 0002.

## Contrato

1. `POST /api/v1/events` continua exigindo API key e retorna 201/200/409 conforme
   o contrato de UUID existente. Somente um novo `FAULT_CONFIRMED` pode enfileirar.
2. A transação bloqueia dispositivo e depois máquina antes da inserção do evento.
   A decisão de ciclo e os alertas são persistidos na mesma transação. Erro na
   fila desfaz também o evento; o produtor pode retransmitir o UUID.
3. O último `FAULT_CONFIRMED`/`FAULT_RECOVERED` persistido para a máquina define
   o ciclo, por ID crescente. Datas fornecidas pelo produtor não reordenam esse
   histórico. Outros tipos de evento e acknowledge não encerram a falha.
4. Com falha ativa, outros UUIDs são registrados como eventos, mas não geram
   alertas. Somente uma recuperação persistida permite um novo ciclo.
5. Em novo ciclo, selecionam-se destinatários ativos em `alert_recipients` para
   `TELEGRAM_ENABLED=true` ou `EMAIL_ENABLED=true`. Não há fallback de destino,
   seed, destinatários fictícios ou suporte a SMS/WhatsApp nesta etapa.
6. Cada destinatário elegível gera um `PENDING`, com `sent_at` e `error_message`
   nulos, salvo se estiver em cooldown. Registros distintos de destinatários
   são independentes mesmo se compartilham o mesmo endereço.

## Cooldown e configuração

`ALERT_COOLDOWN_SECONDS` é obrigatório quando existe canal habilitado. Aceita
segundos finitos >= 0, sem default no código. Zero desabilita somente o intervalo;
a proteção por ciclo e UUID continua ativa. O usuário escolheu **300 segundos**
para o ambiente local. `.env.example` mantém o campo vazio para exigir escolha
explícita de cada ambiente; Compose encaminha a variável ao backend.

O intervalo vale por **máquina + recipient_id + canal** e considera qualquer
registro de alerta anterior (PENDING, SENT ou FAILED). É medido desde a criação
do registro, usando relógio PostgreSQL após adquirir o bloqueio. Na fronteira
exata do intervalo o destinatário volta a ser elegível. Não se usa `started_at`
do sensor nem o início da transação como relógio de cooldown.

Falha persistente não é reenviada após cinco minutos. Uma nova recuperação é
necessária. Ciclos suprimidos por cooldown não são adiados para envio posterior.
Destinatários adicionados ou canais habilitados durante uma falha não causam
envio retroativo. Replays de eventos antigos nunca recriam alertas.

Se os canais estiverem desabilitados, não é exigido cooldown. Se a configuração
da fila for inválida ao processar um novo ciclo, a API retorna 503 com mensagem
genérica e desfaz o evento. A validação é feita nessa operação, não no healthcheck.
Credenciais e validação de destino pertencem aos providers e não bloqueiam a
persistência da fila nesta etapa; falhas de envio serão tratadas na parte 6.3.

## Concorrência e limites

O bloqueio por máquina serializa ingestões por dispositivos diferentes daquela
máquina até commit/rollback. Máquinas diferentes podem avançar independentemente.
Não foi adicionada UNIQUE em alerts: múltiplos registros continuam permitidos
para futuras tentativas explícitas. A proteção atual se aplica ao caminho de
ingestão da aplicação; inserções diretas por SQL não recebem essa garantia.

Nenhuma alteração é inferida em Machine.status, heartbeat ou severidade. Não há
novos campos, tabelas, migrations ou dependências. A fila usa os índices de
machine_id, event_id e recipient_id existentes; testes são funcionais, não de carga.

## Validação

`test_alert_queue.py` cobre persistência, replay, conflito, ciclos, ordem de
chegada, canais/destinatários elegíveis, cooldown por status e destinatário,
fronteira temporal, falha atômica, configuração inválida, máquinas independentes
e concorrência entre dispositivos. Schemas PostgreSQL isolados são removidos
por rollback ou limpeza da fixture. Nenhum provider é chamado por essa lógica.

```powershell
docker compose config --quiet
docker compose build backend
docker compose run --rm --no-deps backend python -m pytest -q
docker compose up -d --wait backend
```

A etapa seguinte é processamento da fila; não está implementada nesta entrega.
