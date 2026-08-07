# Contrato de API — Autenticação Launcher (Fase 2)

Implementação de `bot/docs/LIMERENCE_LAUNCHER_ARCHITECTURE.md` seção 3 e das
pendências 1/3/4/5 da seção 11 (escopadas a auth). Roda embarcado no processo
do bot (`api/main.py: create_app`), prefixo `/auth`.

Regras que este contrato cumpre (não negociáveis, vindas do pedido original):

- Client secret do Discord nunca sai de `bot/config/settings.py` (env var do
  processo do backend).
- Token do Discord nunca chega no Launcher — é trocado, usado uma vez pra
  buscar `/users/@me` e descartado (`services/auth_service.py:
  _exchange_and_fetch_discord_user`).
- Launcher só conhece JWT emitido por este backend.

## Por que "Device Authorization" e não OAuth direto

Discord não implementa RFC 8628 (Device Authorization Grant). O backend
simula: `device_code`/`user_code` são gerados aqui, e quem fala PKCE de
verdade com o Discord é o próprio backend (gera `code_verifier`/
`code_challenge`, guarda o verifier em memória, troca o `code` pelo token
Discord). O Launcher nunca lida com criptografia OAuth — só abre o navegador
e faz poll.

## Rotas

### `POST /auth/device/code`
Rate limit: 10 req / 5 min por IP.

Request:
```json
{"device_uuid": "uuid", "os_info": "Windows 11 Pro", "launcher_version": "0.1.0"}
```
Response `200`:
```json
{
  "device_code": "opaco, usado só pro poll",
  "user_code": "XXXX-XXXX",
  "verification_uri": "https://<public_base_url>/auth/device/authorize?user_code=XXXX-XXXX",
  "expires_in": 600,
  "interval": 5
}
```

### `GET /auth/device/authorize?user_code=XXXX-XXXX`
Sem auth. Valida o `user_code`, gera PKCE + `state` (ligados ao `device_code`
em memória) e responde `307` pro Discord (`https://discord.com/oauth2/authorize?...`).
`404` se o código não existe/expirou.

### `GET /auth/discord/callback?code&state`
Chamada pelo Discord (redirect do navegador), não pelo Launcher. Valida
`state` (proteção CSRF — sem isso, um atacante poderia injetar seu próprio
`code` na sessão de outra pessoa), troca `code`+`code_verifier` pelo token
Discord, busca `/users/@me`, faz upsert de `Player`/`Device`, cria
`LauncherSession`, emite JWT. Rate limit: 30 req / 5 min por IP. Responde
HTML estático (`200` sucesso / `400` falha) — não redireciona pro Launcher,
o Launcher descobre o resultado via poll.

### `POST /auth/device/token`
Poll do Launcher, respeitando `interval` (mínimo 5s entre polls do mesmo
`device_code` — poll mais rápido devolve `slow_down` sem contar como erro).
Rate limit: 120 req / 5 min por IP (defesa extra além do `slow_down`).

Request: `{"device_code": "..."}`

Response `200`, `status` em
`authorization_pending | slow_down | success | expired_token | access_denied`:
```json
{"status": "success", "access_token": "...", "refresh_token": "...", "token_type": "Bearer", "expires_in": 900}
```
Em `success`, o `device_code` é consumido — poll seguinte devolve `expired_token`
(replay protection: cada device_code entrega o par de tokens uma única vez).

### `POST /auth/refresh`
Rate limit: 30 req / min por `ip+device_uuid`.

Request: `{"refresh_token": "...", "device_uuid": "uuid"}`

Sempre rotaciona: token antigo é revogado (`revoked_reason=rotated`), novo
par é emitido. Se o `refresh_token` apresentado já estava revogado (reuso —
sinal de roubo), **toda** a `LauncherSession` do device é derrubada e um
`AuditLogLauncher.REFRESH_REUSE_DETECTED` é gravado — não só aquele token.

Erros (`401` salvo indicado): `invalid_refresh_token`, `session_hijack_suspected`,
`refresh_token_expired`, `device_revoked` (`403`).

### `POST /auth/logout`
Rate limit: 20 req / min por IP. Request: `{"refresh_token": "..."}`. `204`
sempre — idempotente, não revela se o token existia (evita enumeração).

### `POST /auth/logout/all`
Requer `Authorization: Bearer <access_token>`. Revoga toda `LauncherSession`
ativa de todos os `Device` do player (logout em todos os dispositivos).
Response: `{"sessions_revoked": N}`.

### `GET /auth/me`
Requer Bearer. Retorna `Player` resolvido a partir do JWT (id, discord_id,
discord_username, linked_at, last_login_at). Usado pelo Launcher pra
confirmar sessão e pelos testes de rota protegida.

## Claims do JWT (access token)

HS256, `JWT_SECRET_KEY` (env, obrigatório). TTL 900s (`JWT_ACCESS_TTL_SECONDS`).

| Claim | Significado |
|---|---|
| `sub` | `player_id` (UUID) |
| `device_id` | UUID do `Device` |
| `sid` | UUID da `LauncherSession` — correlação/auditoria, não usado pra revogar em tempo real (token é stateless de propósito, TTL curto é a mitigação) |
| `jti` | UUID único do token, correlação em log |
| `iat`/`exp` | emissão/expiração |
| header `kid` | `"v1"` — campo `LauncherSession.jwt_key_id` já grava isso, pronto pra rotação de chave sem migration nova |

Refresh token: opaco (`secrets.token_urlsafe(48)`), TTL `REFRESH_TOKEN_TTL_DAYS`
(default 30), guardado como hash sha256 em `LauncherSession.refresh_token_hash`
— o backend nunca reconstitui o valor em claro a partir do banco.

## Rate limiting

In-memory, janela deslizante (`core/rate_limiter.py`), por instância do
processo (a API roda embarcada no bot, uma instância só — sem Redis no stack
atual). `429` com header `Retry-After`.

| Bucket | Limite | Chave |
|---|---|---|
| `device_code` | 10 / 5min | IP |
| `poll` | 120 / 5min | IP |
| `refresh` | 30 / min | `ip:device_uuid` |
| `logout` | 20 / min | IP |
| `callback` | 30 / 5min | IP |

## `AuditLogLauncher` — metadata por `action`

Tabela global (sem FK, sobrevive à linha referenciada — mesmo padrão de
`AuditLogEntry`). `player_id`/`device_id` nullable (falha de login antes de
existir Player).

| action | metadata |
|---|---|
| `LOGIN_SUCCESS` | `{"discord_id": "..."}` |
| `LOGIN_FAILED` | `{"reason": "discord_exchange_failed"}` |
| `REFRESH_ROTATED` | `{"old_session_id": "...", "new_session_id": "..."}` |
| `REFRESH_REUSE_DETECTED` | `{"reused_session_id": "..."}` |
| `LOGOUT` | `{}` |
| `LOGOUT_ALL` | `{"sessions_revoked": N}` |
| `DEVICE_REVOKED` | `{"reason": "device_mismatch_or_revoked"}` |
| `RATE_LIMITED` | não persistido (só log) — ver nota abaixo |

Hits de rate limit **não** geram linha em `AuditLogLauncher`: persistir a
cada hit abriria um vetor de amplificação (atacante spamma requests só pra
inchar a tabela de auditoria). Vão pro log estruturado
(`core/logger.get_logger("auth_service")`) via `logger.warning`.

## Variáveis de ambiente novas

```
DISCORD_OAUTH_CLIENT_ID=
DISCORD_OAUTH_CLIENT_SECRET=
DISCORD_OAUTH_REDIRECT_URI=   # opcional, default: {PUBLIC_BASE_URL}/auth/discord/callback
JWT_SECRET_KEY=               # obrigatório, >=32 bytes recomendado
JWT_ACCESS_TTL_SECONDS=900    # opcional
REFRESH_TOKEN_TTL_DAYS=30     # opcional
```

## Fora de escopo desta fase

Rotação de múltiplas chaves JWT simultâneas (campo `kid`/`jwt_key_id` já
existe, só não há segunda chave ativa ainda), manifest/download/update do
launcher, loja/licenças (essas rotas já existem no schema — `Product`/
`License` — mas não são consumidas por este contrato).
