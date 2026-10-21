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
