# Fase 8.1 — base de integração

Esta entrega prepara comunicação HTTP, configuração pública e CORS. A página de
bootstrap permanece; não há login, persistência de tokens, renovação, roteamento,
dashboard, abertura de WebSocket ou envio de alertas pelo frontend nesta etapa.

## Configuração

No `.env` da raiz, usado pelo Compose:

```dotenv
CORS_ALLOWED_ORIGINS='["http://localhost:5173","http://127.0.0.1:5173"]'
VITE_API_BASE_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000/api/v1/ws/events
```

Esses valores locais reutilizam as origens já aprovadas e a porta 8000 verificada
no ambiente; não são defaults no código. Ajuste explicitamente em outro ambiente.
`CORS_ALLOWED_ORIGINS` é independente de `WS_ALLOWED_ORIGINS`. Ambas devem conter
as origens reais do navegador, incluindo protocolo e porta. CORS não substitui
autenticação. Sem configuração CORS válida, `python -m app.server` recusa iniciar
com mensagem sanitizada. A configuração é carregada uma vez por processo;
alterações exigem recriação do serviço.

A API base é uma origem HTTP/HTTPS, sem `/api/v1`, credenciais, query ou fragmento.
A URL WS aponta a `/api/v1/ws/events` no mesmo host/porta do backend, com WS para
HTTP ou WSS para HTTPS. Não se usa o hostname interno Docker `backend` no navegador.

Variáveis `VITE_*` são públicas e incorporadas ao build. Nunca incluir JWT_SECRET,
DEVICE_API_KEY, SMTP ou DATABASE_URL nelas. Compose encaminha apenas as duas URLs
como argumentos de build e variáveis do serviço frontend. Mudanças exigem rebuild
dos artefatos estáticos e reinício do servidor de desenvolvimento.

Execução nativa Windows: copiar `frontend/.env.example` para `frontend/.env.local`
e preencher as duas URLs; não copiar o `.env` de segredos da raiz para o frontend.
Arquivos `.env*` locais estão ignorados no Git e excluídos do contexto Docker;
somente o exemplo sem valores é incluído. Dev e build validam as URLs; testes
unitários usam configurações isoladas.

## Política HTTP

Middleware CORS da Starlette já existente na stack FastAPI. Permite origens exatas,
GET/POST/PATCH/DELETE e headers Authorization/Content-Type (além dos headers simples
do protocolo CORS). Expõe Retry-After ao navegador. Cookies não são habilitados;
o contrato atual é Bearer explícito. Não permite X-API-Key no preflight: o navegador
não recebe a chave de dispositivos. Solicitações sem Origin continuam válidas.

Uma origem não permitida não recebe autorização de leitura pelo navegador. CORS
não é firewall nem impede clientes externos de chamar a API; JWT/RBAC continuam
obrigatórios. Falhas de rede e bloqueios CORS não podem ser diferenciados com
certeza pelo Fetch do navegador.

## Cliente compartilhado

- `src/config.ts`: validação das URLs públicas.
- `src/api/client.ts`: Fetch tipado, JSON, query, cancelamento com AbortSignal e 204.
- `src/api/errors.ts`: erros HTTP/rede/cancelamento/resposta inválida/requisição inválida.
- `src/api/index.ts`: criação do cliente configurado e contrato/decoder de saúde.

Cada chamada JSON exige um decoder `(unknown) => T`; não há cast genérico que
declare uma resposta desconhecida como válida. Contratos de domínio serão
adicionados junto às telas que os consomem. Exemplo para uma consulta explícita:

```typescript
import { configuredApi, decodeHealth } from "./api";
const api = configuredApi();
const result = await api.request("/ready", decodeHealth);
```

O cliente preserva false/zero em filtros, omite null/undefined, rejeita destinos
externos, credenciais na URL e números não finitos no corpo. Bearer é fornecido
explicitamente por chamada. Usa `credentials: omit`, `cache: no-store` e rejeita
redirecionamentos. Não registra headers, tokens ou corpos; não guarda respostas
brutas nos erros. Para 422 retém apenas localização e tipo de validação, sem
input/ctx/msg recebidos. Mensagens de apresentação são locais, em português.

401/403/404/409/422/429/503 têm mensagens próprias; outros HTTP preservam status
com mensagem genérica. Retry-After inteiro é disponibilizado, sem retry automático.
O cliente não navega para login, não apaga sessão, não renova tokens nem repete
gravações. Essas decisões pertencem à etapa 2 e às telas. Não há timeout arbitrário:
cancelamento é responsabilidade do consumidor por AbortSignal.

## Dependências e limite da auditoria

Vite 6.4.4 → 6.4.6; Vitest 4.1.11 → 4.1.12, com lockfile atualizado. Nenhuma
nova biblioteca direta. Fetch evita dependência HTTP adicional; React Router e
Recharts ficam para as entregas que os utilizarão.

As correções dos avisos de Vite e do mocker de Vitest foram aplicadas. Em
2026-11-17, a auditoria completa ainda reporta a vulnerabilidade transitiva de
picomatch (ReDoS, GHSA-fc5q-39xc-vjpf), sem versão corrigida publicada. Os avisos
propagam-se pelas ferramentas de desenvolvimento. `npm audit --omit=dev` retornou
zero, mas isso não elimina o risco do servidor Vite usado pelo Compose local.
O bind local verificado permanece 127.0.0.1; não foi executado `audit fix --force`
nem downgrade para versões antigas sugeridas pelo npm. A auditoria completa não
está limpa e deve ser repetida quando houver correção publicada.

Referências: [CORS no FastAPI](https://fastapi.tiangolo.com/tutorial/cors/),
[variáveis públicas no Vite](https://vite.dev/guide/env-and-mode),
[aviso picomatch](https://github.com/advisories/GHSA-fc5q-39xc-vjpf).

## Próxima entrega

Antes de iniciar a etapa 2, retomar a definição da sessão: persistência após reload,
ciclo de 30 minutos, confirmação com 60 segundos, limite do refresh e logout local
versus revogação no servidor. Nenhuma dessas decisões foi implementada aqui.
