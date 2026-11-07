# Fase 6.1 — providers e configuração

Esta etapa implementa somente `AlertProvider.send(message, destination)`,
`TelegramProvider`, `EmailProvider` e a fábrica `configured_providers()` em
`app.alerts`. Não há chamada automática pela API, worker, retries, cooldown,
integração com eventos ou alterações no banco. Não há extensões WhatsApp/SMS,
conforme a restrição explícita aprovada para esta etapa.

Desde a Fase 6.2, a [fila transacional](alert-queue.md) integra eventos e cooldown,
sem chamar os providers. As limitações acima descrevem o módulo de providers.

## Configuração

Use variáveis de ambiente; `.env.example` contém os nomes, sem credenciais.
O Compose encaminha essas variáveis ao backend. Python executado diretamente
não carrega `.env`. Não imprima `docker compose config` sem `--quiet`, pois a
saída expandida pode conter credenciais.

| Variável | Contrato |
| --- | --- |
| TELEGRAM_ENABLED / EMAIL_ENABLED | `true` habilita; ausente, vazio ou `false` desabilita. Outros valores são rejeitados. |
| TELEGRAM_BOT_TOKEN | Obrigatório para Telegram habilitado; mantido como SecretStr. |
| TELEGRAM_TIMEOUT_SECONDS | Positivo e finito, obrigatório quando habilitado; sem default. |
| SMTP_HOST / SMTP_PORT | Obrigatórios quando habilitado; porta entre 1 e 65535, sem default. |
| SMTP_TLS_MODE | Obrigatório: `starttls` ou `ssl`; sem fallback para texto claro. |
| SMTP_TIMEOUT_SECONDS | Positivo e finito, obrigatório quando habilitado; sem default. |
| SMTP_FROM | Um endereço ASCII simples, obrigatório quando habilitado. |
| SMTP_USER / SMTP_PASSWORD | Ambos preenchidos ou ambos vazios, permitindo relay TLS sem autenticação. |

Os canais são desabilitados por padrão. A fábrica valida somente os canais
habilitados, sem abrir conexões. A validação ocorre ao chamar a fábrica, não
no startup atual da API. Configuração inválida gera `AlertConfigurationError`
sem valores sensíveis. Não há valores operacionais de timeout/porta presumidos.

`destination` é sempre explícito. `TELEGRAM_CHAT_ID` permanece reservado no
exemplo antigo, mas não é utilizado como fallback. Telegram aceita ID numérico
ou nome de canal iniciado por `@`; SMTP aceita um destinatário por chamada,
sem display name, lista ou controles de cabeçalho. Essa validação não verifica
a existência do destinatário.

## Contrato de envio

- Retorno `None`: aceitação pelo provider, não comprovação de entrega/leitura.
- `ProviderError`: código sanitizado, sem resposta remota, token ou senha.
- Telegram usa HTTPX assíncrono, HTTPS fixo, texto simples e uma requisição.
  Não segue redirects, não usa proxy do ambiente e não repete automaticamente.
  Valida resposta `ok`, `result.message_id` e mensagens de 1 a 4096 caracteres.
  O filtro do logger HTTPX remove o token da URL nos logs de requisição.
- E-mail usa `smtplib` em `asyncio.to_thread`, valida certificados e hostname,
  faz STARTTLS antes da autenticação ou usa TLS desde a conexão (`ssl`).
  Assunto fixo: `Machine Monitor — alerta`; corpo em texto simples.
- A negociação de autenticação mantém os métodos suportados pelo `smtplib`.
  Se houver rejeição e os métodos seguintes também falharem, preserva a
  classificação sanitizada da primeira rejeição. Uma autenticação posterior
  bem-sucedida permite o envio. Não abre outra conexão nem repete o envio.
  Respostas EHLO inválidas interrompem a operação antes de autenticar/enviar.
- Timeout SMTP é por operação de socket; não é limite global de duração.
  Cancelar a coroutine não interrompe a thread SMTP em andamento.
- Após aceitação SMTP, falha de fechamento não transforma sucesso em falha.
  Registra apenas `smtp_cleanup_failed`. Se o envio falhou, preserva seu erro.

Erros de entrada/Telegram: `invalid_message`, `invalid_destination`,
`invalid_email_input`, `telegram_rejected` e `delivery_unconfirmed`.

Classificação SMTP, também preservada em `alerts.error_message` pelo worker:

| Código | Significado |
| --- | --- |
| `email_connection_failed` | Falha ao estabelecer a sessão SMTP; envio não iniciado. |
| `email_tls_failed` | Falha de TLS/certificado ou STARTTLS indisponível; envio não iniciado. |
| `email_protocol_failed` | Falha na negociação EHLO; envio não iniciado. |
| `email_auth_rejected` | Servidor rejeitou autenticação; não implica necessariamente senha incorreta. |
| `email_app_password_required` | Rejeição 534 com exigência explícita de senha de aplicativo. Outras respostas 534 continuam como rejeição genérica. |
| `email_auth_unavailable` | Servidor não oferece autenticação compatível. |
| `email_auth_connection_failed` | Falha durante login sem rejeição anterior conhecida; envio não iniciado. |
| `email_rejected` | Rejeição SMTP explícita durante envio, incluindo destinatário recusado. |
| `delivery_unconfirmed` | Falha durante `send_message` sem confirmação conclusiva; pode haver aceitação. Também usado pelo worker para exceções inesperadas. |

O provider não retorna nem registra o texto remoto, usuário, senha ou payload.
Somente a classificação sanitizada da primeira rejeição é preservada. Não altera
registros históricos classificados antes desta correção. Nenhum desses códigos
autoriza retry automático, inclusive falhas anteriores ao envio.

Para Gmail com login por senha, a conta pode exigir senha de aplicativo. O código
diagnostica essa exigência, mas não cria credenciais nem contorna a política do
provedor. EMAIL_ENABLED deve estar habilitado para operação normal; alterar `.env`
não atualiza o ambiente de containers que já estão em execução.

## Validação e limites

```powershell
docker compose config --quiet
docker compose build backend
docker compose run --rm --no-deps backend python -m pytest -q tests/test_alert_providers.py
docker compose run --rm --no-deps backend python -m pytest -q
docker compose up -d --wait backend
```

Os testes usam credenciais fictícias, HTTPX MockTransport e SMTP simulado.
Verificam sucesso, falhas, limites, ausência de retries de envio, parâmetros TLS,
thread, redaction e fechamento. A regressão de autenticação executa `login/auth`
reais da biblioteca com apenas o transporte substituído: primeira rejeição seguida
de desconexão, timeout, nova rejeição ou sucesso, nos dois modos TLS. Não enviam
mensagens externas e não validam
handshake TLS real, credenciais de produção ou recebimento em caixa/chat.
Esses ensaios externos dependem de configuração e autorização específicas.

HTTPX 0.28.1 já existia nos testes e passou a dependência de execução para
Telegram. SMTP utiliza a biblioteca padrão, sem dependência adicional.

Na Fase 6.3, o [worker separado](alert-worker.md) chama esses providers após
reservar a tentativa no banco. A API continua sem enviar diretamente.
