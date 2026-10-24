# 0005 — Providers isolados da Fase 6.1

Status: implementado dentro do escopo aprovado de providers e configuração.

## Contexto

A Fase 6 prevê Telegram, e-mail e prevenção de duplicidade. Sua primeira
subetapa autoriza somente os providers. O usuário excluiu explicitamente as
extensões WhatsApp/SMS, apesar da previsão genérica do master prompt.

## Decisão

Contrato assíncrono `send(message, destination)` com sucesso por aceitação e
erros sanitizados. HTTPX existente passa a runtime para Telegram; SMTP usa
stdlib em thread. Canais exigem habilitação explícita. Porta, TLS e timeouts
são configurados, sem default operacional. TLS SMTP é obrigatório; autenticação
é opcional para relay e exige usuário/senha em conjunto quando utilizada.

Destinos são explícitos, sem fallback de chat. Texto simples e assunto de
e-mail fixo nesta subetapa. A fábrica não faz I/O nem é chamada pela API ainda.
Nenhuma mudança no modelo, schema, migration ou contrato REST.

## Consequências

Os providers não implementam retries nem decidem persistência/cooldown.
Aceitação não comprova recebimento. Falhas ambíguas e cancelamento SMTP não
autorizam reenvio automático. Fechamento SMTP não sobrescreve resultado do
envio; eventuais falhas geram aviso sanitizado.

Detalhes de operação, validação e limitações em [providers.md](../providers.md).
