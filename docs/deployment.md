# Execução da Fase 0

> Esta página registra o bootstrap. No checkout com a Fase 2, as quatro variáveis
> JWT também são obrigatórias para Compose. Configure-as conforme
> [authentication.md](authentication.md), que contém o comando de seed manual.
> As credenciais ADMIN são usadas somente no comando de seed, não no serviço.
> Na Fase 3, DEVICE_API_KEY também é obrigatória no Compose. Consulte
> [equipment.md](equipment.md); o heartbeat usa X-API-Key.

## Escopo e pré-requisitos

Bootstrap local: FastAPI, PostgreSQL e React/TypeScript/Vite. Docker com Compose
e suporte a contêineres Linux é necessário para o aceite integrado.
Git e navegador completam os pré-requisitos. Sem Docker, o desenvolvimento
individual exige Python 3.11 e Node.js 22 com npm.

As imagens escolhidas são Python 3.11, Node.js 22 e PostgreSQL 17. São escolhas
de versões de bootstrap, não requisitos previamente definidos no documento mestre.
As tags das imagens ainda não estão fixadas por digest. As versões Python
resolvidas estão em `backend/constraints.txt`.
O frontend usa `package-lock.json` e `npm ci`. O override de Vite mantém a mesma
versão no aplicativo e no Vitest, dentro da faixa compatível declarada pelo Vitest,
evitando a resolução de outra versão principal pelas ferramentas de teste.
O frontend usa o servidor de desenvolvimento Vite: este Compose é para uso local.

## Configuração no Windows / PowerShell

Execute na raiz do repositório:

```powershell
Copy-Item .env.example .env
```

Não sobrescreva um `.env` existente. Preencha-o antes de executar:

| Variável | Conteúdo exigido |
| --- | --- |
| POSTGRES_DB / POSTGRES_USER / POSTGRES_PASSWORD | Banco e credenciais escolhidos localmente |
| DATABASE_URL | URI `postgresql://USUARIO:SENHA@postgres:5432/BANCO` com os mesmos dados; codifique caracteres especiais da URI |
| BACKEND_PORT / FRONTEND_PORT | Duas portas distintas, disponíveis, entre 1024 e 65535 |
| BIND_ADDRESS | Interface local escolhida para publicar os serviços |
| HEALTHCHECK_INTERVAL / TIMEOUT / START_PERIOD | Durações aceitas pelo Compose, com unidade, definidas pelo operador |
| HEALTHCHECK_RETRIES | Inteiro positivo definido pelo operador |

Use um endereço de loopback em BIND_ADDRESS para restringir o acesso ao próprio
computador. Não foram escolhidas portas externas, credenciais ou durações pelo
agente. A porta 5432 é a porta interna padrão da imagem PostgreSQL e não é
publicada no host. Variáveis de autenticação e alertas permanecem vazias e não
são consumidas nesta fase. Não publique nem compartilhe o `.env`.

```powershell
docker compose config --quiet
docker compose up --build -d --wait
docker compose ps
```

`docker compose up` também inicia os três serviços depois da configuração.
O backend aguarda o banco saudável; o frontend aguarda `/ready` do backend.
Se as credenciais de um volume já inicializado mudarem, a imagem PostgreSQL não
reconfigurará automaticamente os usuários. Preserve o volume e investigue a
configuração, sem excluir os dados para contornar o problema.

Abra `http://localhost:<FRONTEND_PORT>` usando a porta escolhida.
Backend: `http://localhost:<BACKEND_PORT>/health`.
Swagger e ReDoc: `/docs` e `/redoc` na mesma origem do backend.
`/health` retorna `{"status":"ok"}`; `/ready` faz `SELECT 1` e retorna 503 se
a configuração/conexão PostgreSQL falhar. Nenhum schema é criado nesta fase.

Para encerrar preservando os dados:

```powershell
docker compose down
```

## Estrutura efetiva

- `backend/`: API mínima e testes; Dockerfile inclui ferramentas de teste locais.
- `frontend/`: página inicial, teste e build TypeScript/Vite.
- `firmware/`, `serial-bridge/`: somente marcadores de diretório.
- `database/init/`, `database/seed/`: somente marcadores; nenhum SQL.
- `docs/`: execução e validação do bootstrap.

Não há simulador executável nesta fase. Nenhum hardware é necessário.

## Providers opcionais — Fase 6.1

Os canais Telegram/e-mail permanecem desabilitados por padrão. Os providers não
são acionados pela API nesta etapa. Para configuração, variáveis obrigatórias e
limites de envio, consulte [providers.md](providers.md). Alterações em `.env`
exigem recriação do container para chegar ao ambiente do processo; nunca
versione credenciais. O healthcheck da API não valida esses serviços externos.

Na Fase 6.2, habilitar um canal permite enfileirar alertas para destinatários
ativos já existentes no banco. Configure também `ALERT_COOLDOWN_SECONDS`, sem
default (300 segundos foi a escolha explícita para o ambiente local).
Não há worker nem envio nesta fase. Veja [alert-queue.md](alert-queue.md).

## Worker opcional — Fase 6.3

O processamento separado foi adicionado na Fase 6.3. Antes de atualizar o backend,
aplique `docker compose run --rm --no-deps backend python -m alembic upgrade head`
com a imagem reconstruída. Configure `ALERT_POLL_INTERVAL_SECONDS` (10 segundos
foi o valor aprovado para este ambiente). A migration é aditiva, sem remover dados.

O worker não inicia no `docker compose up` comum. Consulte [alert-worker.md](alert-worker.md)
para ativação explícita do perfil, teste sem envio e administração manual.
Não ativar canais reais em smoke tests: o worker pode consumir filas existentes.

## WebSocket — Fase 7.1

Antes de recriar o backend, preencher WS_AUTH_TIMEOUT_SECONDS,
WS_SEND_TIMEOUT_SECONDS, WS_MAX_MESSAGE_BYTES e WS_ALLOWED_ORIGINS conforme
[websocket.md](websocket.md). São obrigatórias e não têm defaults. No ambiente
local, foram aprovados 10s, 5s, 4096 bytes e as origens localhost/127.0.0.1 na
porta 5173. O `.env.example` mantém esses campos sem valores operacionais.

O Dockerfile inicia `python -m app.server`, preservando a porta BACKEND_PORT e
um único processo. Esse entrypoint configura transporte WebSocket, limite de
mensagem e filtros de logs; para execução direta no Windows, exportar as mesmas
variáveis e executar esse comando em `backend/`. Não há nova migration.

Após build/testes, atualizar somente a API com
`docker compose up -d --no-deps --wait backend`. Isso não ativa o perfil alerts.
O WebSocket compartilha a porta da API.

## Publicação WebSocket — Fase 7.2

Preencher também `WS_CLIENT_QUEUE_SIZE`, inteiro positivo obrigatório e sem default.
O valor local aprovado é `100` mensagens por conexão. Recriar somente o backend
após build e testes, usando o comando acima. Não há nova dependência ou migration.
A API publica eventos críticos após commit, com filas por cliente e entrega
transitória em um único processo. Reconexão exige atualização por REST; não executar
múltiplos workers/réplicas esperando broadcast compartilhado. Veja [websocket.md](websocket.md).
