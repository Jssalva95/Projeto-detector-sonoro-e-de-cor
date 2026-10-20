# Base de persistência — Fase 1

SQLAlchemy 2.0 foi escolhido entre as alternativas permitidas no mestre. O driver
psycopg existente é reutilizado. DATABASE_URL continua aceitando a URI PostgreSQL
da Fase 0; a seleção de `postgresql+psycopg` é interna e preserva credenciais e
parâmetros, inclusive percent-encoding. Nenhuma alteração no `.env` é necessária.

## Camadas

- `app/models/base.py`: registro declarativo.
- `app/models/domain.py` e `enums.py`: sete modelos e valores enumerados aprovados.
- `app/schemas/domain.py`: contratos de criação/leitura; datas com fuso convertidas
  para UTC; representação de leitura do usuário sem password_hash.
- `app/database/session.py`: engine e contexto de sessão (commit/rollback/close).
- `app/repositories/database.py`: consulta de disponibilidade.
- `app/services/availability.py`: tratamento de indisponibilidade/configuração.
- `app/schemas/health.py`: schema tipado da resposta já existente.
- `app/api/health.py`: adaptações HTTP, mantendo `/health` e `/ready`.

`check_database()` continua disponível para comandos existentes. Readiness usa o
mesmo engine SQLAlchemy que será utilizado pelos modelos. Não existe create_all
na aplicação, nem execução automática de DDL durante startup.

## Migração de base

`0001_backend_baseline` inicia o histórico Alembic e não contém DDL de domínio.
Alembic cria sua tabela técnica `alembic_version`, com coluna `version_num`
VARCHAR(32) NOT NULL, PK `alembic_version_pkc` e índice da PK. Não há FKs ou
relações ORM nessa tabela técnica. A revision é registrada pelo Alembic.

A migration `0002_domain_models`, sucessora da baseline, cria `users`, `machines`,
`devices`, `sensor_readings`, `events`, `alert_recipients` e `alerts`.
Colunas, nulabilidade, relações ORM, FKs, índices e CHECKs estão detalhados no
[contrato aprovado](database-proposal.md). Cada tabela tem PK `id` BIGINT identity.
Todas as FKs usam RESTRICT em exclusão e atualização.

`sound_amplitude` é DOUBLE PRECISION sem limite 0..1 em leituras/eventos.
`color_confidence` permanece entre 0 e 1. A troca de máquina do dispositivo não
reescreve a máquina histórica da ocorrência. `alerts` permite várias tentativas
para o mesmo evento/destinatário/canal; nenhum envio foi implementado.

## Executar no Docker (PowerShell, raiz do projeto)

```powershell
docker compose build backend
docker compose run --rm --no-deps backend python -m alembic upgrade head
docker compose up -d --wait backend
docker compose exec -T backend python -m alembic current
docker compose exec -T backend python -m alembic check
docker compose exec -T backend python -m pytest -q
```

O banco precisa estar saudável antes de executar a migration. O volume é preservado.
`upgrade head` pode ser repetido sem inserir outra versão ou reaplicar a baseline.
Credenciais são lidas do ambiente; alembic.ini não contém URL nem segredos.

No Windows sem Docker, instale requirements-dev.txt no ambiente virtual existente,
entre em backend e execute `python -m alembic upgrade head` com DATABASE_URL no
ambiente apontando a um PostgreSQL acessível. Não imprima a URI em logs.

## Testes de persistência

Os testes usam uma tabela **temporária de teste**, criada via operações Alembic na
conexão dedicada. Um modelo isolado dos metadados da aplicação testa inserção,
commit, releitura, rollback e violação de PK. Fechar a conexão elimina a tabela;
nenhum dado fictício é inserido em tabelas públicas. O teste de versão confirma
a revisão de domínio aplicada. `test_domain.py` cria um schema com nome aleatório
em transação, aplica a migration nesse schema e testa os sete modelos, schemas,
constraints, reassociação e tentativas de alertas. O rollback final remove schema,
dados e sequências de teste, sem inserir fixtures nas tabelas públicas.
O downgrade é testado somente nesse schema isolado. Não executar downgrade em
banco com dados reais.

## Resultado histórico da infraestrutura, anterior aos modelos

- Build da imagem e inicialização do backend: passaram.
- Baseline aplicada e reaplicada; `alembic current`: `0001_backend_baseline (head)`.
- `alembic check`: nenhuma operação nova detectada para os metadados atuais.
- Suíte: 11 testes passaram, nenhum ignorado; persiste o aviso de depreciação
  de BlockingPortal da dependência Starlette/AnyIO já presente na Fase 0.
- Compilação Python e `pip check`: passaram.
- `/health`, `/ready`, `/docs`, `/openapi.json`: HTTP 200.
- PostgreSQL, backend e frontend: healthy.
- Schema público contém somente `alembic_version`; nenhuma tabela de teste restou.
- Credenciais, Compose e volume PostgreSQL não foram alterados.

Os resultados acima registram a etapa inicial. A revisão de domínio atual é
`0002_domain_models`; execute os comandos desta página para validar o estado atual.

## Validação da modelagem aprovada — 20/10/2026

- Build do backend concluído; 36 testes passaram, nenhum ignorado.
- Migration `0002_domain_models` aplicada; segunda execução de upgrade sem alteração.
- `alembic check`: nenhuma divergência detectada entre modelos e banco.
- `compileall` e `pip check`: passaram.
- PostgreSQL e backend healthy; `/health`, `/ready`, `/docs`, `/openapi.json`: HTTP 200.
- Sete tabelas de domínio inspecionadas: colunas, PKs, FKs RESTRICT, índices e CHECKs.
- PostgreSQL reportou `Etc/UTC`. As sete tabelas permanecem sem registros.
- Nenhum schema de teste restou. Volume e credenciais preservados.
- A primeira tentativa de geração falhou porque PostgreSQL estava parado; resolvido
  ao iniciar o serviço existente. Um teste teve autoflush antes de preencher todos
  os campos de reconhecimento; corrigida a fixture sem relaxar a constraint.
- Permanece apenas o aviso de depreciação Starlette/AnyIO já existente.
