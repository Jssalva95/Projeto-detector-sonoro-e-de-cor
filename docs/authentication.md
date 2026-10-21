# Fase 2 — autenticação

Contrato aprovado: login JSON, JWT access/refresh separados, refresh reutilizável
até expirar, autorização pelo usuário ativo e role atual no PostgreSQL, seed manual.
Nenhum endpoint de cadastro ou funcionalidade da Fase 3 foi adicionado.

## Configuração

Defina no `.env` local, sem versionar:

- `JWT_SECRET`: segredo HMAC existente; não há valor padrão.
- `JWT_ALGORITHM`: algoritmo explícito. Suportados HS256, HS384 e HS512, com chave
  de pelo menos 32, 48 e 64 bytes respectivamente; nunca selecionado pelo cliente.
- `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`: duração positiva do access.
- `JWT_REFRESH_TOKEN_EXPIRE_MINUTES`: duração positiva do refresh, sem default.

Compose exige as quatro configurações. A aplicação rejeita configuração inválida
com HTTP 503 nas operações de autenticação. `/health` continua verificando liveness
e `/ready` continua verificando PostgreSQL, conforme o contrato da Fase 0.

## API

| Método/rota | Entrada | Saída |
| --- | --- | --- |
| POST `/api/v1/auth/login` | JSON `email`, `password` | `access_token`, `refresh_token`, `token_type: bearer`, `expires_in` em segundos |
| POST `/api/v1/auth/refresh` | JSON `refresh_token` | `access_token`, `token_type: bearer`, `expires_in` em segundos |
| GET `/api/v1/auth/me` | `Authorization: Bearer <access>` | UserRead, sem senha/hash |

Login procura email sem distinguir maiúsculas/minúsculas, seguindo o índice
`lower(users.email)`. Entrada pública recebe senha, nunca `password_hash`.
`UserCreate` da Fase 1 continua sendo contrato interno de persistência; não é
exposto como endpoint de cadastro. O schema de login é separado.

Claims obrigatórios: `sub` (ID interno em string), `iat`, `exp`, `token_type`.
Access e refresh são verificados com assinatura, expiração e finalidade estrita.
Refresh não autentica `/me`; access não pode renovar tokens. Cada requisição
protegida e cada refresh consultam o usuário no banco. Usuários inexistentes ou
inativos são rejeitados. Roles não são copiados para claims, evitando permissões
obsoletas. RBAC usa `require_roles(...)` com ADMIN, OPERATOR e VIEWER; permissões
de recursos futuros não foram antecipadas.

Refresh não é rotacionado, não é armazenado no banco e não tem revogação individual.
O mesmo refresh pode gerar access tokens até expirar, enquanto o usuário existir
e estiver ativo. Desativação bloqueia ambos os tokens enquanto persistir; reativar
o usuário permite novamente tokens ainda válidos. Trocar a senha não revoga tokens.

Tokens completos são devolvidos somente nas respostas previstas de login/refresh;
não são registrados em logs nem incluídos em mensagens de erro. Respostas de sucesso
usam `Cache-Control: no-store`. Credenciais inválidas têm resposta genérica 401;
permissão insuficiente, 403; payload inválido, 422; configuração/banco indisponível,
503. Erros de validação da autenticação não ecoam payloads.

No Swagger, execute login e use o access token no botão Authorize (HTTP Bearer).
Nunca publique capturas ou saídas que contenham tokens ou senhas.

## Seed manual

Configure `ADMIN_NAME`, `ADMIN_EMAIL`, `ADMIN_PASSWORD` no `.env` local.
Essas variáveis não entram no serviço backend permanente. Para executar manualmente
na raiz do projeto (PowerShell):

```powershell
docker compose run --rm --no-deps --env-from-file .env backend python -m app.seed_admin
```

O comando exige Compose com suporte a `run --env-from-file`. Alternativamente,
com as três variáveis já presentes no ambiente do shell:

```powershell
docker compose run --rm --no-deps -e ADMIN_NAME -e ADMIN_EMAIL -e ADMIN_PASSWORD backend python -m app.seed_admin
```

Não passe senhas como argumentos literais. No Windows com Python local, a partir
de `backend`, use `python -m app.seed_admin` com DATABASE_URL e as três variáveis
ADMIN já definidas no ambiente. A aplicação não carrega `.env` automaticamente.

O seed grava Argon2id com salt, role ADMIN e usuário ativo. Se o email já existir,
retorna código 1 e não altera nome, senha, role ou atividade. Não há seed automático,
credenciais padrão, usuário fictício de produção ou nova migration.

## Dependências e validação

PyJWT 2.15.1 e pwdlib 0.3.0 com Argon2. Dependências transitivas fixadas em
`backend/constraints.txt`: argon2-cffi, argon2-cffi-bindings, cffi e pycparser.

```powershell
docker compose build backend
docker compose run --rm --no-deps backend python -m pytest -q
docker compose up -d --wait backend
docker compose exec -T backend python -m alembic current
docker compose exec -T backend python -m alembic check
docker compose exec -T backend python -m pip check
```

Testes usam o schema PostgreSQL transacional da Fase 1, removido por rollback.
Incluem seed e duplicidade, hashing, login, tokens inválidos/expirados/trocados,
desativação/exclusão, refresh reutilizável, alteração de role e proteção de logs.
Uma rota exclusiva da aplicação de teste verifica RBAC sem criar endpoint de
produção fora do escopo. Configurações JWT de teste são fixtures independentes
dos secrets reais. Não executar downgrade no banco real.

Fontes: [FastAPI](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/),
[PyJWT](https://pyjwt.readthedocs.io/en/stable/usage.html),
[pwdlib](https://frankie567.github.io/pwdlib/reference/pwdlib/).
