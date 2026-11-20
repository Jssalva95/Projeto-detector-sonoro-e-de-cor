# ADR 0013 — Continuidade do login no navegador

Status: aprovado pelo usuário; implementação na etapa 2 da Fase 8.

## Decisão

Preservar JWT access de 30 minutos e refresh de 60 minutos na configuração local,
sempre obtendo as durações do backend. Não apresentar aviso de presença, contador
de 60 segundos ou limite adicional de inatividade. O usuário aprovou cookies
HttpOnly e os ajustes de autenticação, CORS e proteção CSRF necessários ao F5.

As rotas JSON/Bearer existentes permanecem compatíveis. Adicionar o transporte
de navegador em `/api/v1/auth/browser/{login,session,logout}` (POST). Login e
session retornam access, tipo, validade restante e usuário público. Refresh nunca
é retornado no JSON desse transporte. O frontend mantém access apenas em memória.

Dois cookies HttpOnly, `mm_access` e `mm_refresh`, permitem restaurar também um
access ainda válido quando o refresh já expirou. Path limitado às rotas browser,
sem Domain, SameSite=Strict, Secure em HTTPS. HTTP só é aceito em loopback local.
Os cookies expiram junto com os JWTs. Restaurar access válido não reescreve
cookies. Renovar access nunca altera o refresh ou sua data de expiração.

As três rotas exigem Origin exata autorizada e `X-CSRF-Protection: 1`. O cabeçalho
não é segredo: exige preflight e, junto com a checagem de origem, impede pedidos
de formulários externos. CORS permite credenciais somente para origens explícitas.
Frontend e API devem usar o mesmo protocolo e hostname; portas podem diferir.
Este requisito é mais restrito que SameSite e evita inferir domínios registráveis.

## Interface e concorrência

O controlador único compartilha a sessão entre rotas. Restauração/renovação é
single flight. Login, restauração e logout serializam alterações de cookies;
Web Locks coordenam essas operações entre abas quando disponíveis. BroadcastChannel
invalida o estado das outras abas após login/logout quando suportado.
Respostas anteriores a logout/troca de sessão não podem repopular dados na UI.

A interface verifica a sessão ao iniciar, voltar ao foco, recuperar a conexão e
ao vencer o access. Usa a validade recebida da API, incluindo tempo de rede de
forma conservadora. Uma falha de rede/503 bloqueia a confirmação de acesso com
opção de tentar novamente, sem apagar cookies como se fossem credenciais inválidas.
Um 401 definitivo solicita login. Consultas GET podem ser repetidas uma vez após
renovação; gravações não são reenviadas automaticamente.

Não armazenar tokens, senhas ou dados do usuário em localStorage/sessionStorage.
Somente um marcador booleano de logout pendente usa sessionStorage, para impedir
restauração silenciosa após F5 quando a saída não pôde ser confirmada pela rede.
Se esse armazenamento estiver indisponível, o marcador só existe em memória.

## Limites preservados

Logout apaga cookies e estado local, mas não revoga cópias de JWTs: permanece o
contrato anterior, sem tabela de sessões, rotação ou revogação individual. Uma
sessão de outro navegador não é encerrada. Web Locks/BroadcastChannel são apoio
entre abas da mesma origem, não uma garantia de revogação no servidor.
Cookies HttpOnly evitam a leitura direta pelo JavaScript, mas não tornam XSS inofensivo.

O refresh vencer aos 60 minutos impede novas renovações; não invalida um access
emitido anteriormente. F5 e navegação não reiniciam prazos.
Autorização continua sendo feita pelo backend, com usuário ativo e role atual.

Sem migration ou alteração de credenciais. `/session` no frontend mostra somente
os dados da conta atual e permite exercitar navegação. `/dashboard` é apenas a
estrutura da página; métricas e funcionalidades das próximas entregas não foram
antecipadas.

Referências: [cookies](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie),
[CSRF](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).
