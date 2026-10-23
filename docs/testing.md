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
