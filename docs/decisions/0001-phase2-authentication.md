# Autenticação da Fase 2

Status: aprovado pelo usuário e implementado.

## Contexto

A Fase 1 define `users`, roles e unicidade de email. A Fase 2 exige login, JWT,
refresh, RBAC e seed administrativo. O usuário aprovou explicitamente os contratos
que não estavam detalhados no documento mestre.

## Decisão

- Reutilizar `users`; não criar migration, cadastro público ou tabelas de sessão.
- Login JSON, access/refresh distintos e `/me` via HTTP Bearer.
- Claims `sub` (ID interno string), `iat`, `exp`, `token_type`.
- Consultar usuário ativo e role atual no banco; validar finalidade do token.
- Refresh reutilizável até expirar, sem rotação ou revogação individual.
- Durações configuradas no ambiente, incluindo refresh obrigatório sem default.
- Seed somente manual, com ADMIN_NAME/EMAIL/PASSWORD e sem sobrescrever existentes.
- Hashing Argon2id via pwdlib; assinatura/verificação via PyJWT.

## Consequências

Desativar/excluir usuário bloqueia acesso e renovação. Não existe invalidação por
sessão, logout ou troca de senha nesta fase. Roles são avaliados pelo estado atual
do banco. Tokens somente aparecem nas respostas de autenticação previstas, nunca
em logs ou erros. Nenhuma permissão de máquinas/dispositivos foi antecipada.

Detalhes operacionais e limitações: [authentication.md](../authentication.md).
