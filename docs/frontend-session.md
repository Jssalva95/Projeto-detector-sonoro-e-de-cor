# Fase 8.2 — Login, sessão e navegação

Contrato: [ADR 0013](decisions/0013-browser-session.md). A escolha de cookies
HttpOnly e a retirada do aviso aos 30 minutos foram aprovadas pelo usuário.

## Executar

Preservar as durações existentes em `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` e
`JWT_REFRESH_TOKEN_EXPIRE_MINUTES`. Nenhum tempo de sessão é definido no frontend.

```powershell
docker compose build backend frontend
docker compose up -d --no-deps --wait backend frontend
```

Com a configuração local atual, acessar `http://localhost:5173` (API em
`http://localhost:8000`). Não misturar frontend em `127.0.0.1` com API em
`localhost`; a aplicação apresenta mensagem de configuração nesse caso. Para
usar outro hostname, configurar as URLs públicas, CORS e WS de forma consistente
e recriar as imagens. Fora do loopback, HTTPS é obrigatório. Em reverse proxy,
configurar corretamente os headers encaminhados e confiar somente no proxy real.
O servidor que hospedar o build estático deve encaminhar as rotas do frontend ao
`index.html`. O Compose atual continua utilizando Vite para desenvolvimento local.

Login usa um usuário real já existente; não cria contas ou seeds automáticos.
Trocar de página preserva o estado em React. F5 restaura a sessão dos cookies sem
mostrar o formulário antes da resposta. Access expirado é renovado se o refresh
continuar válido; se não houver credenciais válidas, aparece o login.

## API de navegador

Todas as rotas abaixo são POST e exigem Origin aprovada, mesmo esquema/hostname
da API e `X-CSRF-Protection: 1`. Fetch usa credentials=include somente nesse
transporte. Recursos existentes continuam com Bearer e credentials=omit.

| Rota | Entrada | Comportamento |
| --- | --- | --- |
| `/api/v1/auth/browser/login` | JSON email/password | Emite os dois cookies; retorna access_token, token_type, expires_in e user. |
| `/api/v1/auth/browser/session` | Sem corpo | Revalida usuário e access; se necessário, renova com refresh. Retorna a mesma estrutura pública. |
| `/api/v1/auth/browser/logout` | Sem corpo | Apaga ambos os cookies; retorna 204. Não revoga JWTs no servidor. |

As rotas antigas `/api/v1/auth/login`, `/refresh` e `/me` continuam disponíveis.
Não se deve usar o login JSON antigo como alternativa silenciosa ao fluxo browser.
Nenhum refresh, senha ou hash é exibido pela interface. O ID interno do usuário é
preservado; o decoder rejeita IDs fora da precisão inteira segura de JavaScript,
em vez de usar silenciosamente um ID arredondado.

## Componentes e testes

- `src/auth/contracts.ts`: contratos e decoders de respostas desconhecidas.
- `src/auth/transport.ts`: chamadas HTTP de sessão.
- `src/auth/session.ts`: estado, expiração, renovação e controle de concorrência.
- `src/auth/browser.ts`: configuração, coordenação entre abas e marcador de saída.
- `src/auth/context.tsx`: integração com React, foco e prazo do access.
- `src/App.tsx`: login, layout, rotas protegidas e informações da sessão.

React Router DOM 7.18.5 foi adicionado para as rotas previstas na especificação.
Não há biblioteca de armazenamento de JWT ou framework visual adicional.

Testes unitários usam credenciais e tempos isolados. Para validar no Edge real,
a partir da raiz, com os serviços atualizados e ADMIN_EMAIL/ADMIN_PASSWORD locais
correspondentes a uma conta existente:

```powershell
node frontend/tests/browser-session.mjs
```

O script abre perfil isolado, faz login nessa conta, testa navegação/F5/renovação,
cookies, CSRF, layout estreito e logout. Não grava registros no banco nem envia
alertas. Não imprime senhas ou tokens. Remove cookies apenas desse perfil de teste;
não espera 30/60 minutos e não altera as durações reais. Expiração criptográfica
é verificada pelos testes do backend; o navegador simula o desaparecimento dos
cookies expirados. Capturas ficam em `.tools/` ignorado pelo Git e podem conter
nome/email da conta de teste, portanto não devem ser publicadas sem revisão.

O roteiro também verifica navegação por teclado, recuperação após perda de rede
e propagação de logout para outra aba. Os resultados efetivamente executados
estão em [testing.md](testing.md). Fechar uma aba não equivale a revogação no
servidor; os prazos dos cookies/JWT continuam sendo respeitados.
