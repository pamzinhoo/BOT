# Fase futura — Segurança para publicar o painel web

Status: anotado como fase futura. Nao implementar agora enquanto a Fase 4 nao estiver 100% fechada.

## Contexto

O painel web hoje foi feito para uso local. A seguranca atual depende de ele estar acessivel apenas em `127.0.0.1`/ambiente local, usando `require_local_admin`.

Antes de colocar o painel na internet, ele precisa deixar de confiar no acesso local e passar a exigir autenticacao, autorizacao por permissao e auditoria real de usuario.

## Arquitetura recomendada

Fluxo ideal:

```text
Internet
-> HTTPS / Cloudflare ou proxy seguro
-> Discord OAuth2
-> validar usuario logado
-> validar se esta no servidor
-> validar cargos/permissoes permitidos
-> sessao segura em cookie HttpOnly/Secure/SameSite
-> CSRF em rotas de escrita
-> auditoria com usuario real
-> API administrativa
```

## Regras obrigatorias antes de publicar

1. `WEB_ADMIN_ENABLED=false` por padrao.
2. Em ambiente publico, nenhuma rota administrativa pode aceitar apenas IP/local check.
3. Login via Discord OAuth2, preferencialmente usando `identify` e validacao pelo bot/cache da guild.
4. Sessao em cookie `HttpOnly`, `Secure` e `SameSite=Lax` ou `Strict`.
5. Nada de token sensivel em `localStorage`.
6. Middleware unico para proteger `/admin/api/*`.
7. Autorizacao por acao, nao apenas por pagina escondida no frontend.
8. CSRF obrigatorio para `POST`, `PATCH`, `PUT` e `DELETE`.
9. Rate limit em login, callback OAuth e rotas sensiveis.
10. CORS fechado para o dominio oficial do painel.
11. Bloquear `/docs`, `/redoc` e endpoints internos em producao publica.
12. Auditoria precisa registrar o usuario real, nao apenas `Painel web`.

## Niveis sugeridos

```text
OWNER
- acesso total
- configuracoes sensiveis
- pagamentos, planos, DLCs
- permissoes do painel

ADMIN
- tickets
- staff
- paineis
- sorteios
- auditoria

MANAGER
- tickets
- staff
- avaliacoes
- ranking

SUPPORT
- ler, assumir, liberar e fechar tickets
- sem acesso a dinheiro/configuracoes

VIEWER
- apenas leitura
```

## Permissoes por rota/acao

Exemplos:

```text
ticket:read
ticket:write
ticket:delete
staff:read
staff:write
settings:read
settings:write
billing:read
billing:write
dlc:read
dlc:write
giveaway:read
giveaway:write
audit:read
system:read
```

## Plano de implementacao futuro

### Fase Segurança 1 — Chave de modo publico

- Criar `WEB_ADMIN_ENABLED=false` por padrao.
- Se estiver falso, manter comportamento local atual.
- Se estiver verdadeiro, exigir sessao autenticada.

### Fase Segurança 2 — OAuth Discord

- Criar rotas:
  - `GET /admin/login/discord`
  - `GET /admin/auth/callback`
  - `POST /admin/logout`
  - `GET /admin/api/me`
- Salvar sessao web em tabela propria.
- Validar usuario/guild/cargos.

### Fase Segurança 3 — Middleware de autorizacao

- Trocar o uso publico de `require_local_admin` por `require_admin_session`.
- Permitir local sem login apenas em ambiente local.
- Exigir permissao por rota em ambiente publico.

### Fase Segurança 4 — CSRF e rate limit

- CSRF para rotas de escrita.
- Rate limit por IP e por usuario autenticado.
- Logar IP e user-agent em tentativas sensiveis.

### Fase Segurança 5 — Auditoria real

- Acoes do painel precisam gravar:
  - Discord user id do admin
  - nome do admin
  - IP aproximado
  - user-agent
  - acao executada
  - alvo alterado
- Parar de usar `Painel web` como executor generico nas rotas publicas.

## Decisao atual

Nao publicar o painel na internet ate esta fase ser implementada. Por enquanto, manter local.