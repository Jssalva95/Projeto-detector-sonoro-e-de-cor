# Validação da Fase 0

## Backend local

Na raiz, PowerShell (sem necessidade de ativar scripts):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
Push-Location backend
..\.venv\Scripts\python.exe -m pytest -q
..\.venv\Scripts\python.exe -m compileall -q app tests
Pop-Location
```

O teste de integração PostgreSQL é explicitamente ignorado se DATABASE_URL não
estiver no ambiente do processo. Os testes restantes verificam liveness sem
banco, readiness sem configuração e falha de conexão sem exposição de detalhes.
O `.env` é lido pelo Compose; não é carregado automaticamente pelo Python.

## Frontend local

```powershell
Push-Location frontend
npm ci
npm run test
npm run typecheck
npm run build
Pop-Location
```

Não há linter configurado nesta fase. `typecheck` é verificação estática de tipos,
não deve ser reportado como lint. O teste renderiza a página e verifica que ela
não apresenta monitoramento real como funcionalidade já disponível.

## Integração com Compose

Após configurar `.env` conforme deployment.md:

```powershell
docker compose config --quiet
docker compose up --build -d --wait
docker compose exec backend python -m pytest -q
docker compose exec frontend npm run test
docker compose exec frontend npm run build
docker compose exec backend python -c "import os, urllib.request; print(urllib.request.urlopen('http://localhost:' + os.environ['BACKEND_PORT'] + '/health').read().decode())"
docker compose exec backend python -c "from app.database.connection import check_database; assert check_database()"
docker compose ps
```

No Compose, DATABASE_URL está presente: o teste PostgreSQL não deve ser ignorado.
O build do frontend também ocorre durante a construção da imagem.
Confira a página no navegador usando a porta configurada.

## Critério de aceite

Os três serviços devem iniciar, o frontend deve responder, `/health` deve retornar
200 com status ok, e a conexão PostgreSQL real deve passar. Criação de arquivos,
compilação Python e testes com banco simulado não bastam para concluir a fase.

## Resultado da execução inicial

- Backend: 3 testes passaram; 1 teste PostgreSQL ignorado por ausência de DATABASE_URL.
- Compilação sintática Python e `pip check`: passaram.
- Uvicorn iniciado localmente e `/health` verificado por HTTP real: 200, status ok.
- Frontend: 1 teste passou; TypeScript e build Vite passaram.
- Vite iniciado localmente: página inicial respondeu HTTP 200.
- Auditoria npm após correções de versões: zero vulnerabilidades reportadas.
- As verificações HTTP usaram portas temporárias atribuídas pelo sistema operacional;
  não definem portas de execução do projeto. Os servidores de teste foram encerrados.
- Node.js 22.15.0 foi baixado em `.tools/` (ignorado); não houve instalação global.
- Docker/Compose não encontrados no PATH nem no caminho usual de Docker Desktop.
  Imagens, configuração Compose e integração PostgreSQL permanecem sem validação real.
- Não houve validação visual em navegador. Teste HTTP não equivale a teste visual.

A Fase 0 permanece com aceite integrado pendente. Configure `.env` e execute os
comandos de integração acima em um ambiente com Docker operacional.

## Fase 1 — infraestrutura de persistência

A seção de resultado inicial acima é histórica. O deployment integrado da Fase 0
foi validado posteriormente. Para a base da Fase 1, consulte `database.md` e
aplique `alembic upgrade head` antes de executar a suíte no backend atualizado.

```powershell
docker compose exec -T backend python -m alembic current
docker compose exec -T backend python -m alembic check
docker compose exec -T backend python -m pytest -q
docker compose exec -T backend python -m compileall -q app tests alembic
docker compose exec -T backend python -m pip check
```

`test_phase1.py` cobre credenciais codificadas na URI usando somente fixtures,
configuração inválida sem exposição de segredos, contratos HTTP/OpenAPI,
commit/releitura ORM, rollback, violação de PK e baseline aplicada. A tabela de
teste é temporária e desaparece ao fechar a conexão. `test_domain.py` valida os
modelos aprovados em schema isolado, removido por rollback: persistência e schemas
das sete tabelas, amplitude bruta, UTC, CHECKs, unicidade, FKs RESTRICT, histórico
após reassociação e múltiplas tentativas em alerts. Também valida upgrade/downgrade
nesse schema isolado. Nenhum envio, ingestão ou autenticação é executado.

## Fase 2 — autenticação

`test_auth.py` adiciona 46 casos aos 36 testes anteriores. Configurações JWT são
fixtures, e os usuários de teste ficam no schema isolado, removido por rollback.
O seed real é manual e está documentado em [authentication.md](authentication.md).

Validação realizada nesta implementação:

- `docker compose build backend`: passou.
- `docker compose run --rm --no-deps backend python -m pytest -q`: 82 passaram,
  nenhum ignorado. Persiste o aviso Starlette/AnyIO já existente.
- Login, `/me` e refresh repetido: HTTP 200 em requisições reais ao backend.
- Access enviado ao refresh e refresh enviado ao `/me`: HTTP 401.
- Usuários desativados/excluídos, roles alterados e tokens expirados/inválidos:
  cobertos por testes PostgreSQL sem alterar o administrador real.
- Migrations continuam em `0002_domain_models`; `alembic check` sem divergências.
- Nenhuma rota de teste RBAC é exposta na aplicação de produção.

Não imprimir as respostas de login/refresh durante testes manuais: elas contêm os
tokens previstos no contrato. A API não registra esses valores nos logs.

## Fase 3 — máquinas, dispositivos e heartbeat

`test_equipment.py` acrescenta 33 casos aos 82 existentes. Resultado da suíte:
115 testes passaram, nenhum ignorado. Os testes usam os routers reais com JWT,
RBAC e API key, além do PostgreSQL isolado já utilizado nas fases anteriores.

Cobrem criação, listagem, busca, PATCH e DELETE de ambas as entidades; restrições
de referências e duplicidade; associação inexistente; reassociação preservando
histórico; campos internos bloqueados; roles e usuários inativos; heartbeat em
UTC, atualização/preservação de firmware, credenciais incorretas, dispositivo
inativo, máquina incompatível e payload inválido. OpenAPI verifica rotas e esquemas
de segurança. Nenhuma fixture é gravada nas tabelas públicas.

Comandos e contrato: [equipment.md](equipment.md).

## Fase 4 — telemetria

Antes da implementação, a Fase 3 foi revalidada: 115 testes passaram, nenhum
ignorado; serviços healthy; Alembic 0002 sem divergência. Hashes dos arquivos
Python de app, tests e alembic coincidiram entre checkout e container.

`test_readings.py` acrescenta 41 casos. Resultado completo: **156 passaram,
nenhum ignorado**, com o mesmo aviso de depreciação Starlette/AnyIO.

Cobertura: persistência/releitura, UUID obrigatório e duplicado, savepoint após
conflito, UTC, amplitude bruta, sound_trigger nullable, validações de payload,
máquina/dispositivo ausente, dispositivo inativo, associação incompatível e
preservação histórica após reassociação. Filtros individuais e combinados,
limites inclusivos, false booleano, lista vazia, paginação padrão/máxima e
desempate por ID. JWT access/refresh, roles atuais, usuário inativo, API key,
ausência de efeitos em status/heartbeat/eventos/alertas e contratos OpenAPI.
Os testes são transacionais; não são ensaio de carga ou concorrência em produção.

Comandos executados com sucesso:

```powershell
docker compose config --quiet
docker compose build backend
docker compose run --rm --no-deps backend python -m pytest -q
docker compose up -d --wait backend
docker compose exec -T backend python -m alembic current
docker compose exec -T backend python -m alembic check
docker compose exec -T backend python -m pip check
docker compose exec -T backend python -m compileall -q app tests alembic
docker compose exec -T frontend npm run test
docker compose exec -T frontend npm run typecheck
docker compose exec -T frontend npm run build
docker compose ps
git diff --check
git diff
git status --short
```

Backend e PostgreSQL healthy; frontend healthy, teste único, typecheck e build
passaram. Sem novas migrations/dependências. Alembic permanece 0002_domain_models
(head), sem operações novas detectadas. Não há lint configurado.

Smoke HTTP via script Python em `docker compose run --rm -T --no-deps
--env-from-file .env backend python -`: /health, /ready, /docs e /openapi.json
retornaram 200. Login, /me e listagens autenticadas de máquinas, dispositivos e
leituras retornaram 200. Sem autenticação/refresh em GET e POST sem chave: 401;
limit inválido e POST vazio com chave: 422; leitura inexistente: 404. Nenhum
token, senha ou resposta de login foi impresso. A persistência válida do POST foi
validada pelo TestClient com PostgreSQL isolado, sem inserir dados na produção.

Após a suíte, não restaram schemas test_domain; tabelas públicas machines,
devices, sensor_readings, events e alerts continuaram vazias. Índices de
machine_id, device_id, timestamp e UUID foram confirmados no banco real.

Contrato e limites: [readings.md](readings.md). Nenhuma validação física pertence
a esta fase; não houve integração com sensores reais.

### Correções após auditoria da Fase 4

A auditoria posterior encontrou duas lacunas na suíte inicial: amplitude não
finita causava 500 e offset acima de BIGINT causava 503. Correções aprovadas:
amplitude finita e offset limitado a 9223372036854775807, com retorno 422.
O handler evita ecoar infinito quando um número JSON como 1e309 sofre overflow.

Oito casos permanentes foram acrescentados em test_readings.py: cinco strings
não finitas/overflow, dois números JSON com overflow e a fronteira BIGINT do
offset. Entradas de amplitude rejeitadas não persistem leituras. A suíte existente
continua verificando amplitude bruta negativa e acima de 1.

Validação desta correção:

- `docker compose build backend`: passou.
- `docker compose run --rm --no-deps backend python -m pytest -q`: **164 passaram**,
  nenhum ignorado; permanece o aviso preexistente Starlette/AnyIO.
- `docker compose config --quiet` e `docker compose up -d --wait backend`: passaram.
- `docker compose exec -T backend python -m alembic current`: 0002_domain_models (head).
- `docker compose exec -T backend python -m alembic check`: sem divergências.
- `docker compose exec -T backend python -m pip check`: sem incompatibilidades.
- `docker compose exec -T backend python -m compileall -q app tests alembic`: passou.
- `docker compose ps`: backend, PostgreSQL e frontend healthy.
- Smoke HTTP via Python no Compose: /health, /ready, /docs e /openapi.json 200;
  offset 0 e máximo BIGINT 200; offset acima do máximo 422; amplitude NaN,
  Infinity, -Infinity e overflow textual/numérico 422. Sem dados de produção
  inseridos, sem tokens impressos e sem schemas de teste remanescentes.
- `git diff`, `git diff --check` e `git status --short`: revisados.

Nenhuma dependência ou migration adicionada. Contratos de eventos preservados.
As duas pendências identificadas foram resolvidas; frontend não foi modificado.

## Fase 5 — eventos

Contrato aprovado: [events.md](events.md). A suíte completa contém **227 testes
passando**, nenhum ignorado: 164 anteriores, 60 casos HTTP/contrato de eventos e
3 casos de concorrência PostgreSQL. Persiste apenas o aviso Starlette/AnyIO.

test_events.py valida persistência, UTC, tipos/severidades sem inferência,
idempotência normalizada (incluindo null e reconhecimento posterior), conflitos
sem sobrescrita, reassociação histórica, dispositivo inativo, filtros, paginação,
roles, finalidade JWT, API key, reconhecimento pelo servidor e ausência de
efeitos em Machine.status, heartbeat, leituras e alertas. Inclui valores não
finitos e offset acima do limite BIGINT. Schema transacional removido por rollback.

test_event_concurrency.py executa transações em conexões independentes: UUID
idêntico resulta em uma ocorrência; UUID com dados divergentes em dispositivos
distintos resulta em um vencedor e um conflito; reconhecimento concorrente por
dois usuários preserva um único responsável/horário. Utiliza schema privado
test_events_<uuid>, confirmado para permitir visibilidade entre conexões e removido
no finally por downgrade da migration e DROP SCHEMA sem CASCADE. Não usa tabelas
públicas. São testes funcionais de concorrência, não ensaios de carga.

Comandos executados:

```powershell
docker compose build backend
docker compose run --rm --no-deps backend python -m pytest -q
docker compose config --quiet
docker compose up -d --wait backend
docker compose exec -T backend python -m alembic current
docker compose exec -T backend python -m alembic check
docker compose exec -T backend python -m pip check
docker compose exec -T backend python -m compileall -q app tests alembic
docker compose exec -T frontend npm run test
docker compose exec -T frontend npm run typecheck
docker compose exec -T frontend npm run build
docker compose ps
git diff --check
git diff
git status --short
```

Build e verificações passaram. Backend, PostgreSQL e frontend healthy; Alembic
0002_domain_models (head), sem divergências. Frontend: 1 teste, typecheck e build
passaram. Não há lint configurado. Sem novas dependências ou migrations.

Smoke HTTP via script Python no Compose, sem imprimir credenciais/tokens:
/health, /ready, /docs e /openapi.json 200; listagem autenticada de eventos 200;
registro ausente (consulta/acknowledge) 404; ausência de credenciais e refresh
na consulta 401; POST vazio com API key e offset acima do máximo 422.
POST válido e acknowledge de registros existentes foram exercitados com banco
isolado nos testes, sem introduzir ocorrências fictícias nas tabelas públicas.

Após execução: zero schemas test_domain/test_events remanescentes; tabelas
públicas machines, devices, sensor_readings, events e alerts vazias. Índices de
events confirmados no banco real. Não houve alteração do volume, credenciais,
schema de produção ou integração física. Fase 6 não implementada.

### Correções de validação após auditoria da Fase 5

Três pendências corrigidas: overflow ao converter datas para UTC, NUL em message
e serialização de erros contendo infinito fora do campo sound_amplitude.
test_validation_boundaries.py acrescenta 23 casos: datas extremas em eventos,
leituras e filtros; limites UTC ainda representáveis; mensagem NUL; preservação
de Unicode/quebras de linha; erros de enum, campo extra, amplitude e texto com
overflow numérico. Verifica ausência de persistência e requisição válida após erro.

Validação executada nesta correção:

- `docker compose build backend`: passou.
- `docker compose run --rm --no-deps backend python -m pytest -q`: **250 passaram**,
  nenhum ignorado; permanece o aviso preexistente Starlette/AnyIO.
- `docker compose config --quiet` e `docker compose up -d --wait backend`: passaram.
- `docker compose exec -T backend python -m alembic current`: 0002_domain_models (head).
- `docker compose exec -T backend python -m alembic check`: sem divergências.
- `docker compose exec -T backend python -m pip check`: sem incompatibilidades.
- `docker compose exec -T backend python -m compileall -q app tests alembic`: passou.
- `docker compose ps`: todos os serviços healthy.
- Smoke HTTP via script Python no Compose: /health, /ready, /docs e /openapi.json
  200; datas extremas, NUL e overflow em enum/campo extra 422; filtros de datas
  extremos de eventos/leituras 422; consultas válidas posteriores 200.
- `git diff`, `git diff --check` e `git status --short`: revisados.

Sem schemas de teste remanescentes; events e sensor_readings públicos vazios.
Nenhuma migration, dependência ou alteração de credenciais. Frontend não alterado.
As três pendências auditadas foram resolvidas; a Fase 6 não foi iniciada.

## Fase 6.1 — providers e configuração

A observação anterior sobre Fase 6 é histórica. Esta subetapa adiciona
`test_alert_providers.py`: 47 casos de configuração, contratos Telegram/SMTP,
TLS, thread, erros, timeouts, entradas inválidas, ausência de retry e proteção
de segredos. Uma falha de fechamento SMTP após aceitação preserva o sucesso;
após erro de envio preserva o erro original e registra aviso sanitizado.

Validação executada na retomada:

- Local: `..\.venv\Scripts\python.exe -m pytest -q tests/test_alert_providers.py -p no:cacheprovider`
  no diretório backend: 47 passaram.
- `docker compose config --quiet` e `docker compose build backend`: passaram.
- `docker compose run --rm --no-deps backend python -m pytest -q`:
  **297 passaram**, nenhum ignorado; aviso preexistente Starlette/AnyIO.
- `docker compose run --rm --no-deps backend python -m pip check`: sem incompatibilidades.
- `docker compose run --rm --no-deps backend python -m compileall -q app tests alembic`: passou.
- `docker compose up -d --wait backend`: backend atualizado healthy.
- `docker compose exec -T backend python -m alembic current`: 0002_domain_models (head).
- `docker compose exec -T backend python -m alembic check`: sem divergências.
- Smoke via Python/urllib no backend: /health, /ready e /docs retornaram 200;
  providers importados e fábrica com canais explicitamente desabilitados
  retornou dicionário vazio sem I/O externo.
- `docker compose ps`: backend, PostgreSQL e frontend healthy.
- `git diff`, `git diff --check` e `git status --short`: revisados.

Não houve testes de entrega externa, handshake TLS real ou validação de
credenciais reais. HTTP e SMTP foram simulados nos testes específicos.
Frontend não foi alterado; seus testes/build não foram repetidos.
Sem mudanças em migrations, banco, `.env` real ou volume PostgreSQL.
HTTPX 0.28.1 passou de dependência de desenvolvimento para execução.

Escopo e limites: [providers.md](providers.md). Partes 6.2/6.3 não implementadas.

## Fase 6.2 — fila transacional

A limitação anterior sobre 6.2 é histórica. `test_alert_queue.py` acrescenta
22 casos de persistência, ciclos, cooldown, configuração e concorrência.
`conftest.py` desabilita canais no ambiente dos testes por padrão; casos de
fila habilitam explicitamente seus canais e cooldown fictício. Configurações
reais do operador não determinam os resultados nem provocam envios.

A barreira do teste de conflito UUID entre dispositivos foi movida para antes
do bloqueio por máquina, mantendo as assertions de um vencedor/um conflito.
Uma barreira após adquirir esse bloqueio impediria artificialmente a segunda
transação de alcançá-la. Não houve relaxamento das garantias verificadas.

Validação executada:

- `docker compose config --quiet` e `docker compose build backend`: passaram.
- `docker compose run --rm --no-deps backend python -m pytest -q tests/test_alert_queue.py tests/test_event_concurrency.py`:
  25 passaram.
- `docker compose run --rm --no-deps backend python -m pytest -q`:
  **319 passaram**, nenhum ignorado; aviso preexistente Starlette/AnyIO.
- `docker compose up -d --wait backend`: passou.
- `docker compose exec -T backend python -m pip check`: sem incompatibilidades.
- `docker compose exec -T backend python -m compileall -q app tests alembic`: passou.
- `docker compose exec -T backend python -m alembic current`: 0002_domain_models (head).
- `docker compose exec -T backend python -m alembic check`: sem divergências.
- Smoke Python no container: /health, /ready e /docs HTTP 200; cooldown efetivo
  confirmado como 300 segundos, conforme escolha do usuário.
- Consulta somente leitura PostgreSQL: zero schemas test_domain/test_events
  remanescentes. A primeira tentativa teve erro de quoting PowerShell, corrigido
  passando o script via stdin.
- `docker compose ps`: três serviços healthy.
- `git diff`, `git diff --check`, `git status --short`: revisados.
- `git check-ignore .env`: arquivo continua ignorado.

Somente ALERT_COOLDOWN_SECONDS foi configurado no `.env` local; credenciais
preservadas. Não houve migrations, dependências novas, envio externo ou worker.
Testes de persistência usam schemas isolados, sem criar destinatários de produção.
Frontend não foi alterado nem teve sua suíte repetida. A parte 6.3 não foi iniciada.

## Fase 6.3 — worker, tentativas e retomada após interrupção

A observação anterior sobre 6.3 é histórica. O worker, a CLI administrativa,
o template, a migration 0003 e 35 testes de entrega estavam preservados após
a interrupção. A auditoria reexecutou 354 testes com sucesso, mas identificou
uma lacuna: processamentos que não suspendem a coroutine impediam o loop de
executar o callback de parada enquanto a fila permanecesse ocupada.

Na retomada, foram adicionados três testes permanentes em test_alert_delivery.py:
SIGINT e SIGTERM durante processamento imediato, mais o cenário PostgreSQL em
que o primeiro destinatário é inativo e o próximo alerta deve permanecer sem
reserva. Antes da correção, os três falharam: cinco iterações em vez de uma e
consumo indevido do próximo alerta. Após ceder controle com asyncio.sleep(0)
entre itens, os três passaram. Isso não adiciona atraso operacional nem cancela
uma tentativa em andamento.

Validação executada em 2026-11-02:

- Tentativa local de pytest: coleta bloqueada por ausência de alembic.migration
  no venv local. Nenhuma dependência foi instalada; a validação prosseguiu no Docker.
- `docker compose build backend`: passou, inclusive após a correção. O tag
  python:3.11-slim resolveu uma imagem base mais recente; a suíte final foi
  executada sobre a imagem reconstruída, com as dependências do projeto fixadas.
- `docker compose run --rm --no-deps backend python -m pytest -q tests/test_alert_delivery.py -k busy`:
  três falhas reproduzidas antes da correção; depois, três passaram.
- `docker compose run --rm --no-deps backend python -m pytest -q`:
  **357 passaram**, nenhum ignorado; aviso preexistente Starlette/AnyIO.
- `docker compose config --quiet` e `docker compose up -d --wait backend`: passaram.
- `docker compose exec -T backend python -m pip check`: sem incompatibilidades.
- `docker compose exec -T backend python -m compileall -q app tests alembic`: passou.
- `docker compose exec -T backend python -m alembic current`: 0003_alert_attempts (head).
- `docker compose exec -T backend python -m alembic check`: sem divergências.
- Smoke Python no container: /health, /ready, /docs e /openapi.json HTTP 200;
  polling efetivo de 10s e cooldown de 300s confirmados.
- `docker compose run --rm --no-deps -e TELEGRAM_ENABLED=false -e EMAIL_ENABLED=false alert-worker python -m app.alerts.worker --once`:
  inicializou com channels=none e encerrou com código 0.
- `docker compose ps`: backend, PostgreSQL e frontend healthy.
- Consulta PostgreSQL somente leitura: zero schemas de teste remanescentes.
- `git diff`, `git diff --check` e `git status --short`: revisados.

Os testes de entrega cobrem reserva confirmada antes do transporte, ausência de
lock durante o envio, concorrência e SKIP LOCKED, falhas de commit, cancelamento,
resultados incertos sem retry automático, destinatário inelegível, histórico de
tentativas manuais, validação de parâmetros, template e upgrade/downgrade da
migration em schema isolado. Não houve downgrade no banco público.

Nesta retomada não houve alteração do .env, novas dependências, mudanças adicionais
de schema ou envios reais. A migration 0003 já estava aplicada e foi conferida.
Frontend não foi alterado nem teve sua suíte repetida. Entrega real Telegram/e-mail,
TLS externo e carga de produção permanecem não validados. A suíte não garante
ausência de falhas futuras. Operação e limites: [alert-worker.md](alert-worker.md).

## Fase 6.3 — diagnóstico SMTP e validação final em 2026-11-07

O registro de 2026-11-02 acima é histórico. Após aquela validação, o diagnóstico
real identificou uma rejeição SMTP 534 exigindo senha de aplicativo, seguida de
desconexão durante a tentativa de outro método de autenticação. Com a senha de
aplicativo configurada pelo usuário, a autenticação retornou 235. Um envio único
autorizado foi aceito pelo servidor, e o usuário confirmou o recebimento do e-mail
com assunto `Machine Monitor — alerta`. Esse ensaio chamou o provider diretamente;
não comprova o fluxo externo completo de evento, fila e worker.

A correção posterior preserva a classificação sanitizada da primeira rejeição
quando a negociação termina em falha. Se outro método autenticar com sucesso,
o envio continua permitido. Foram separados os códigos de conexão, TLS, EHLO,
autenticação, exigência de senha de aplicativo, destinatário recusado e resultado
incerto durante envio. O worker preserva esses códigos em `alerts.error_message`,
sem registrar respostas remotas ou segredos e sem retry automático. Consulte a
tabela de códigos em [providers.md](providers.md).

Na revisão após a interrupção, foram executados:

- `docker compose build backend`: aprovado. A tag Python 3.11-slim resolveu uma
  imagem base mais recente; a suíte foi executada sobre a imagem reconstruída.
- `docker compose run --rm -T --no-deps backend python -m pytest -q`:
  **395 testes passaram**, nenhum ignorado; um aviso preexistente de depreciação
  Starlette/AnyIO. Inclui regressões SMTP e persistência dos novos códigos.
- Em container temporário com canais desabilitados: `python -m pip check`,
  `python -m compileall -q app tests alembic`, `python -m alembic current` e
  `python -m alembic check`: aprovados; migration 0003 no head, sem divergências.
- Inicialização da API nessa imagem: `/health`, `/ready` e `/docs` com HTTP 200.
- Worker `--once` com canais desabilitados: inicializou e encerrou com código 0.
- `git diff --check`, revisão de diff/status e `git check-ignore .env`: sem erros
  de whitespace; alterações existentes preservadas; `.env` permanece ignorado.

## Fase 6.3 — aplicação da imagem validada em 2026-11-07

A revisão encontrou o backend ativo ainda na imagem anterior à correção SMTP.
Após autorização do usuário, a imagem já validada foi aplicada sem novo build
ou alteração de código entre os testes e a implantação. Foram executados:

- `docker compose config --quiet`: configuração válida.
- `docker compose run --rm -T --no-deps backend python -m alembic current`:
  `0003_alert_attempts (head)` já aplicada; não foi necessária nova migration.
- `docker compose up -d --no-deps --wait backend`: backend recriado e healthy.
- Script Python via `docker compose exec -T backend python -B -`: confirmou
  `_AuthenticationDiagnostics`, os sete códigos SMTP adicionais aceitos pelo
  worker e HTTP 200 em `/health`, `/ready` e `/docs` no container atualizado.
  Também executou `python -m pip check`, `python -m alembic current` e
  `python -m alembic check`: sem incompatibilidades ou divergências.
- `docker compose run --rm -T --no-deps -e TELEGRAM_ENABLED=false -e EMAIL_ENABLED=false alert-worker python -m app.alerts.worker --once`:
  inicializou com `channels=none` e encerrou com código 0, usando a imagem atualizada.

PostgreSQL, volume de dados, frontend e `.env` foram preservados. O perfil opcional
do worker não foi ativado para consumo contínuo de filas. Não houve novos envios
reais nessas validações nem repetição da suíte após a alteração apenas documental.
O commit fica a cargo do usuário.

As duas pendências de documentação e aplicação da imagem ao backend estão
resolvidas. Permanecem como limites de validação externa: entrega real pelo
Telegram, fluxo completo evento → fila → worker → destinatário externo e carga
de produção. O recebimento anterior valida o envio direto de e-mail antes da
correção de diagnóstico; a versão corrigida foi validada com transportes simulados.
Esta conclusão não equivale a garantir ausência de falhas futuras nem autoriza
envios externos adicionais. A Fase 7 não foi iniciada.

## Fase 7.1 — conexão e autenticação WebSocket em 2026-11-07

A observação anterior sobre a Fase 7 é histórica. O usuário autorizou somente
a parte 7.1 e confirmou `machine_id` como ID interno, coerente com REST.
O endpoint `/api/v1/ws/events` autentica o access JWT na primeira mensagem,
valida Origin, usuário ativo e role atual, confirma a autenticação e encerra
na expiração. O contrato de eventos está definido, mas ainda não existe
publicação de eventos ou broadcast. Nenhuma migration foi adicionada.

Foi verificado que a instalação mínima do Uvicorn não possuía `websockets` nem
`wsproto`. Adicionado `websockets==17.4`, com importação compatível e transporte
real testado. O entrypoint Docker/Windows `python -m app.server` aplica o limite
de mensagem e protege logs de protocolo. As quatro configurações WS aprovadas
foram acrescentadas ao `.env` local; credenciais foram preservadas e o arquivo
continua ignorado pelo Git. Os campos em `.env.example` não têm defaults.

Validações específicas executadas:

- `docker compose run --rm -T --no-deps --volume ./backend:/app:ro backend python -m pytest -q -p no:cacheprovider tests/test_websocket.py tests/test_websocket_transport.py`:
  **52 testes passaram**, incluindo 4 com Uvicorn real em portas locais livres,
  JWTs fictícios e schemas PostgreSQL isolados. O código foi montado somente
  para leitura durante essa validação.
- Cobertura: roles de leitura, access/refresh, usuário inativo/excluído,
  assinatura/expiração, origem ausente ou inválida, recusa de query,
  mensagens inválidas/binárias/grandes, timeout de autenticação/envio,
  expiração ociosa e durante envio bloqueado, revalidação antes de enviar,
  conexões independentes, sanitização dos logs e contrato de IDs/timestamps.
- A revisão identificou e corrigiu a preservação da tupla usada pelo
  AccessFormatter do Uvicorn: o filtro sanitiza o caminho sem quebrar os logs
  HTTP. Regressão específica e teste real verificam ausência de logging errors.
- `docker compose config --quiet` e `docker compose build backend`: aprovados.
- Script Python no container validou os valores aprovados: autenticação 10s,
  envio 5s, tamanho 4096 bytes e origens localhost/127.0.0.1 na porta 5173.
  Executou `python -m pip check`, `python -m compileall -q app tests alembic`,
  `python -m alembic current` e `python -m alembic check`: sem erros,
  migration 0003 no head e sem divergências de schema.

Validação final e aplicação local da 7.1:

- `docker compose run --rm -T --no-deps backend python -m pytest -q`:
  **447 testes passaram**, nenhum ignorado, incluindo os 52 da 7.1. Permanece
  um aviso preexistente de depreciação Starlette/AnyIO. As execuções intermediárias
  passaram com 445 e 446 testes antes das duas últimas regressões adicionadas.
- `docker compose up -d --no-deps --wait backend`: imagem validada aplicada;
  backend healthy, iniciado por `python -m app.server`.
- Script via `docker compose exec -T backend python -B -`: `/health`, `/ready`
  e `/docs` retornaram 200; conexão WebSocket real no container aceitou o handshake
  com origem permitida e recusou token fictício com código 4401.
- `docker compose ps --all`: backend, PostgreSQL e frontend healthy. Volume e
  credenciais preservados; perfil de alertas não ativado.
- `git diff --check`, `git diff`, `git status --short` e `git check-ignore .env`:
  revisados; sem erros de whitespace, `.env` ignorado e nenhum commit criado.

Contrato, códigos de encerramento e limites: [websocket.md](websocket.md).
Não houve envio externo nem uso de hardware. Execução nativa do Python no Windows
não foi validada; os comandos Docker foram executados pelo PowerShell no Windows.
A publicação pós-commit e a fila de saída pertencem à 7.2 e não foram implementadas.

## Retomada e revalidação da Fase 7.1 — 2026-11-12

A interrupção ocorreu após implementação, testes e aplicação local da 7.1,
antes do relatório final ao usuário. Código, contratos, documentação e testes
estavam preservados; o último commit continua sendo 7f1bbae (Fase 6.3).
Nesta retomada não foi necessário alterar código nem recriar containers.

Verificações realmente executadas:

- `git status --short`, `git log -3 --oneline` e revisão do diff: mudanças da
  7.1 presentes e ainda sem commit; nenhuma implementação da 7.2 adicionada.
- `docker compose config --quiet`: configuração válida.
- `docker compose ps --all`: backend, frontend e PostgreSQL healthy.
- `docker compose exec -T backend python -m pip check`: sem incompatibilidades.
- Comparação SHA-256 entre arquivos locais e container ativo: **75 arquivos Python
  de app/tests conferidos, nenhuma divergência**. Não foi necessário novo build;
  permanece a imagem validada e aplicada na etapa anterior.
- `docker compose run --rm -T --no-deps --volume ./backend:/app:ro backend python -m pytest -q -p no:cacheprovider`:
  **447 testes passaram**, nenhum ignorado, incluindo 52 da 7.1. Permanece somente
  o aviso preexistente Starlette/AnyIO. Fontes locais montadas somente para leitura.
- Script via `docker compose exec -T backend python -B -`: confirmou as quatro
  configurações WS aprovadas, HTTP 200 em `/health`, `/ready` e `/docs`, handshake
  WebSocket e recusa de token fictício com código 4401. Também executou
  `python -m alembic current` e `python -m alembic check`: 0003 no head,
  sem divergências de schema.
- `git diff --check`, revisão de diff/status e confirmação de `.env` ignorado:
  sem erros de whitespace e alterações anteriores preservadas.

Não foram identificadas pendências funcionais bloqueantes no escopo da 7.1 nas
verificações executadas. O commit permanece a cargo do usuário. Publicação
pós-commit, broadcast e filas de saída continuam reservados à 7.2. Não houve
envios externos, mudanças de credenciais, migrations ou validação física nesta
retomada; somente este registro de testes foi atualizado.
