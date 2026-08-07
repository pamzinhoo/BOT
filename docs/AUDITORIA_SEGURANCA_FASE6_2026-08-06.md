# Auditoria de Segurança — Fase 6 (Ecossistema Launcher/Licenciamento)

Data: 2026-08-06
Escopo: tudo construído nas Fases 2–5 — `AuthService`/JWT/refresh tokens
(Launcher), `Product`/`License`/`LicenseService`, `DownloadService`, API HTTP
embarcada (`api/`), integração Backend↔Bot (`EventBus`, `RoleSyncService`,
`ReconciliationService`, `/internal/*`). Não reaudita o escopo do bot Discord
já coberto por `AUDITORIA_SEGURANCA_2026-08-02.md`/`VALIDACAO_POS_AUDITORIA.md`.

Método: revisão categoria por categoria (lista abaixo, pedida explicitamente)
contra o código real — leitura completa dos módulos envolvidos, não
amostragem — correção direta + teste automatizado por achado + suíte
completa rodada no final.

---

## Resumo executivo

| Severidade | Encontrados | Corrigidos |
|---|---|---|
| Alta | 3 | 3 |
| Média | 5 | 5 |
| Baixa | 1 | 1 |
| Revisado, sem achado | 15 categorias | — |

**Testes:** suíte completa 303 passam / 1 falha pré-existente sem relação
(`test_help_views.py`, bot Discord, nada a ver com este escopo) /
`test_audit_fixes_validation.py` requer Postgres real + credenciais Discord
reais (infra ausente neste ambiente de desenvolvimento — já assim antes desta
fase). 60 testes novos/atualizados nesta auditoria.

---

## ALTA

### A1 — Access token sobrevive à revogação de sessão até expirar sozinho
**Categoria do pedido:** Session Hijacking, Token Theft, Sessões, Dispositivos
**Arquivo:** `services/auth_service.py: get_player_from_access_token`
**Causa:** a validação do JWT checava só assinatura + expiração + `player.is_banned`.
Nunca conferia se a `LauncherSession` referenciada pelo claim `sid` continuava
viva. Um JWT é stateless por natureza — revogar a sessão no banco
(`logout`, `logout_all`, `device_mismatch`, `refresh_reuse_detected`) não
invalidava um access token já emitido.
**Risco:** token roubado (device comprometido, log vazado, MITM parcial)
continuava servindo requisições por até `JWT_ACCESS_TTL_SECONDS` (900s / 15min
por padrão) mesmo depois da vítima detectar e fazer logout/logout_all, ou
depois do sistema detectar reuso de refresh token e derrubar a sessão inteira.
**Correção:** `get_player_from_access_token` agora busca a `LauncherSession`
pelo `claims.session_id` e rejeita (`invalid_token`) se ela não existe, está
revogada, ou o `device_id` do claim não bate com o da sessão. Fecha a janela:
revogar a sessão invalida o access token na próxima requisição, não só no
próximo refresh.
**Testado:** `tests/test_auth_service.py` —
`test_get_player_from_access_token_rejects_revoked_session`,
`test_get_player_from_access_token_rejects_device_revoked_via_cascade`,
`test_get_player_from_access_token_rejects_unknown_session`.

### A2 — Nenhuma rota do Launcher/download/webhook/internal tinha rate limit
**Categoria do pedido:** Rate Limiting, Manipulação da API, Download ilegal
**Arquivos:** `api/routes/{download,launcher,player,webhook,internal}_routes.py`
**Causa:** só `/auth/*` (Fase 2) tinha rate limiting (`AuthService.enforce_rate_limit`).
`/download`, `/update`, `/launcher/news`, `/launcher/version`, `/launcher/manifest`,
`/player/licenses`, `/player/products`, `/webhooks/mercadopago` e `/internal/*`
não tinham limite nenhum.
**Risco:** custo de storage amplificável (gerar URL assinada não é grátis —
cada chamada bate no provedor S3-compatível), DoS de baixo esforço contra
qualquer endpoint autenticado ou público, possível scraping de todo o
catálogo/manifest em rajada.
**Correção:** helper `api/dependencies.py: enforce_rate_limit` (mesmo padrão
409/429 já usado em `/auth`), aplicado com limites por rota: `/download`
30/5min por player, `/download/{id}/complete` 60/5min por player, `/update`
30/min por IP (rota pública), `/launcher/news`+`/launcher/version` 60/min por
IP, `/launcher/manifest` 60/min por player, `/player/*` 60/min por player,
`/webhooks/mercadopago` 120/min por IP, `/internal/*` 120/min por IP (defesa
em profundidade — já autenticado por HMAC, mas nada além disso o limitava).
**Testado:** `tests/test_launcher_download_routes.py::test_download_rate_limit_is_enforced`
prova 429 de ponta a ponta (não só a unidade do `RateLimiter`, já coberta em
`tests/test_rate_limiter.py`).

### A3 — Segredos HMAC/JWT sem tamanho mínimo exigido
**Categoria do pedido:** Criptografia, Downgrade Attack, JWT
**Arquivo:** `config/settings.py`
**Causa:** `JWT_SECRET_KEY` e `INTERNAL_API_SECRET` eram aceitos com qualquer
tamanho. HS256 com chave curta é forjável por força bruta offline — o próprio
`pyjwt` já emite `InsecureKeyLengthWarning` pra chave abaixo de 32 bytes (visto
nos logs de teste antes desta correção).
**Risco:** chave fraca em produção permitiria forjar `access_token` pra
qualquer `player_id` (bypass total de auth) ou forjar requisições assinadas
pra `/internal/*` (conceder/remover cargo Discord arbitrariamente).
**Correção:** `Settings.load()` rejeita (`SettingsError`) `JWT_SECRET_KEY`
ou `INTERNAL_API_SECRET` (quando configurado) com menos de 32 bytes — mesmo
mínimo do RFC 7518 §3.2 pra HS256.
**Testado:** `tests/test_settings.py` — 4 casos novos (curto rejeita, exato
32 aceita, pra ambas as chaves).

---

## MÉDIA

### M1 — Replay attack no webhook do Mercado Pago
**Categoria do pedido:** Replay Attack
**Arquivo:** `providers/mercadopago.py: validate_webhook`
**Causa:** o `ts` do header `x-signature` fazia parte do manifest assinado
(então não dava pra forjar um `ts` novo sem o secret), mas nunca era checado
contra o relógio atual — só usado dentro do HMAC. Uma notificação capturada
(proxy comprometido, log vazado) continuava com assinatura válida pra sempre.
**Risco:** replay de um webhook antigo. Impacto de fato limitado porque
`confirm_payment`/`reject_payment`/`expire_payment` já são idempotentes por
status (Fase 1) — um replay de "aprovado" depois de já aprovado cai no
caminho idempotente sem duplicar efeito. Ainda assim, rejeitar na borda é
mais seguro que depender só da idempotência a jusante.
**Correção:** janela de tolerância de 300s (`_WEBHOOK_MAX_AGE_SECONDS`) —
`ts` fora da janela é rejeitado antes mesmo de tocar o banco. Suporta `ts`
em segundos ou milissegundos (Mercado Pago documenta segundos, mas o parser
tolera os dois formatos sem risco, já que a assinatura em si continua sendo
a defesa primária).
**Testado:** `tests/test_mercadopago_provider.py` (arquivo novo — **não
existia nenhum teste pra este provider antes desta auditoria**, apesar de
processar dinheiro real): assinatura válida/fresca aceita, secret ausente,
headers ausentes, assinatura errada, `data_id` adulterado, timestamp
antigo rejeitado, timestamp em ms aceito, timestamp não-numérico rejeitado.

### M2 — Replay attack no canal interno Backend↔Bot
**Categoria do pedido:** Replay Attack, Manipulação da API
**Arquivo:** `api/dependencies.py: verify_internal_signature`
**Causa:** o HMAC original assinava só o corpo cru, sem nenhum componente de
tempo — uma requisição válida capturada (`POST /internal/license-events` ou
`/internal/reconcile`) ficava reenviável pra sempre com a mesma assinatura.
**Risco:** menor que webhook (handlers do outro lado — `RoleSyncService.
handle_license_event`, `ReconciliationService.reconcile_all_guilds` — já são
idempotentes/seguros de rodar de novo), mas ainda assim permite forçar
reconciliação ou reprocessar evento de licença repetidamente sem necessidade.
**Correção:** header `X-Internal-Timestamp` (unix epoch) agora faz parte do
manifest assinado (`f"{ts}.{corpo}"`, não só checado separado — impede
recombinar um timestamp fresco com uma assinatura antiga de corpo diferente),
com janela de 300s.
**Testado:** `tests/test_internal_routes.py` — timestamp ausente, timestamp
não-numérico, timestamp velho rejeitado, assinatura não pode ser recombinada
com outro timestamp, caso de replay dentro da janela documentado como
limitação aceita (HMAC+ts sem nonce não impede replay *imediato*, só limita
a janela — ver nota no próprio teste).

### M3 — Sem CORS explícito
**Categoria do pedido:** CORS
**Arquivo:** `api/main.py`
**Causa:** nenhum `CORSMiddleware` configurado. O comportamento resultante já
era seguro por padrão (FastAPI sem CORS = navegador bloqueia leitura de
resposta cross-origin), mas implícito — não documentado, fácil de "corrigir"
errado no futuro adicionando `allow_origins=["*"]` sem entender a implicação.
**Correção:** `CORSMiddleware` adicionado explicitamente, condicionado a
`CORS_ALLOWED_ORIGINS` (novo, vazio por padrão = nega toda origem cross-site,
igual ao comportamento anterior, mas agora intencional e documentado).
`allow_credentials=False` (a API não usa cookie, só Bearer token — não há
necessidade nem justificativa pra credentials cross-origin).
**Testado:** comportamento coberto indiretamente pelos testes de rota
existentes (nenhum usa `Origin` cross-site, então CORS nunca intercepta);
não há uma superfície CORS testável isoladamente sem um navegador real —
documentado aqui como decisão de configuração, não como lógica de negócio.

### M4 — Download completion sem lock (race condition)
**Categoria do pedido:** Race Conditions
**Arquivo:** `database/repositories/download_repository.py`,
`services/download_service.py: complete_download`
**Causa:** `complete_download` lia o `Download` sem `SELECT ... FOR UPDATE` —
duas chamadas concorrentes (retry do Launcher) pro mesmo `download_id`
podiam ambas passar pela checagem `status == AUTHORIZED` antes de qualquer
uma escrever, resultando em corrida (não em bypass de segurança: o pior caso
é o status final COMPLETED/FAILED oscilar dependendo de qual escrita
"ganha", nunca dupla contabilização nem falsificação de integridade).
**Correção:** `DownloadRepository.get_by_id_locked` (mesmo padrão de
`PaymentRepository`/`LicenseRepository`), usado em `complete_download`.
**Testado:** coberto pela suíte existente de `test_download_service.py`
(idempotência já testada); lock não muda comportamento observável em teste
single-threaded, só fecha a janela sob concorrência real (Postgres).

### M5 — HTTPS não exigido em produção
**Categoria do pedido:** MITM
**Arquivo:** `config/settings.py`
**Causa:** `PUBLIC_BASE_URL` aceitava `http://` mesmo com `ENVIRONMENT=production`.
Esse valor vira a base do `discord_oauth_redirect_uri` e é o que o Launcher
usa pra falar com o backend — token, refresh_token, código OAuth trafegando
sem TLS ficam interceptáveis (MITM).
**Risco:** só se materializa se alguém efetivamente builda infraestrutura de
produção apontando pra uma URL HTTP — mas o código não impedia, e a validação
de infra fica fora do alcance de um app-level fix, exceto recusar subir.
**Correção:** `Settings.load()` rejeita `ENVIRONMENT=production` com
`PUBLIC_BASE_URL` que não comece com `https://`.
**Testado:** `tests/test_settings.py` — produção sem https rejeita, produção
com https aceita, dev continua aceitando http (loopback local).

---

## BAIXA

### B1 — Nenhum teste cobria `MercadoPagoProvider` diretamente
**Categoria do pedido:** Uploads, Testes completos (transversal)
**Achado:** processando pagamentos reais desde a Fase 1, `providers/mercadopago.py`
nunca teve arquivo de teste próprio — só era exercitado indiretamente via
`SubscriptionService`/`WebhookService` com mocks que nunca chamavam
`validate_webhook` de verdade contra um HMAC real.
**Correção:** ver M1 acima — `tests/test_mercadopago_provider.py` cobre o
provider isoladamente agora.

---

## Revisado, sem achado (categorias do pedido sem mudança de código)

| Categoria | Onde foi olhado | Conclusão |
|---|---|---|
| **OAuth** | `auth_service.py` (PKCE S256 obrigatório, `state` como CSRF token, client_secret nunca sai do backend, token do Discord descartado após uso único) | Já sólido (Fase 2), nada a corrigir. |
| **JWT** | `core/security/jwt_service.py` | Algoritmo fixado em lista explícita (`algorithms=["HS256"]"`) — sem isso um JWT `alg=none` seria aceito (downgrade attack clássico). `kid` no header já prepara rotação de chave. |
| **Refresh Tokens** | `auth_service.py: refresh` | Rotação a cada uso + detecção de reuso (revoga sessão inteira do device) + hash SHA-256 no banco (nunca o valor em claro) já implementado na Fase 2. |
| **Downgrade Attack** | jwt_service (alg pinado), PKCE (`S256` hardcoded, "plain" nunca aceito) | Sem vetor de downgrade de protocolo encontrado. |
| **SQL Injection** | Todo o repo (`grep` por SQL cru/f-string em `.execute`) | 100% SQLAlchemy ORM parametrizado — nenhuma query com interpolação de string encontrada em lugar nenhum do projeto. |
| **CSRF** | Toda rota HTTP | API é 100% Bearer token (sem cookie de sessão) — CSRF clássico via navegador não se aplica. Único endpoint navegado por browser (`GET /auth/discord/callback`) já é protegido por `state`. |
| **Enumeração** | `/player/*`, `/download`, `/launcher/manifest` | Nenhuma rota aceita `player_id` arbitrário — sempre derivado do JWT (`get_current_player`). Sem vetor de IDOR/enumeração de outro player. |
| **Uploads** | `grep -r "UploadFile\|multipart"` em `api/` | Nenhum endpoint de upload de arquivo existe. `LauncherNews.cover_image_url` é string gerenciada por staff (Discord), não upload HTTP. |
| **Logs** | `grep` por `logger.*token\|secret\|password` em `services/`, `api/`, `core/`, `providers/` | Nenhuma ocorrência — nenhum segredo/token é logado em lugar nenhum do código auditado. |
| **Permissões** | Todas as rotas HTTP novas (Fases 4–5) | Nenhum endpoint expõe ação administrativa (grant/revoke de licença, gerenciar Product) via HTTP — essas ações continuam exclusivamente Discord-cog-driven (staff), fora do escopo desta API. `/internal/*` não é acionável por player nenhum. |
| **Manipulação da API** | Schemas Pydantic de todas as rotas novas | Validação de tipo/tamanho em toda entrada (`min_length`/`max_length` em `client_sha256`, enums parseados com erro 400 explícito); nenhum endpoint faz mass-assignment de body direto pra ORM. |
| **Download ilegal / Bypass de licenças** | `download_service.py` | `License` ACTIVE reconfirmada em `POST /download` mesmo que `/launcher/manifest` já tenha checado antes (nunca reaproveita checagem — ver `LAUNCHER_API_CONTRACT.md` seção 2). URL sempre assinada, curta duração, nunca servida pelo processo do bot. |
| **Verificação de Integridade** | `DownloadService.complete_download` | SHA-256 do manifest comparado contra o hash calculado pelo Launcher, já implementado na Fase 4. |
| **Sessões / Dispositivos** | `auth_service.py` + A1 acima | Revogação em cascata (device → todas as sessões) já existia; A1 fechou a lacuna de o access token sobreviver à revogação. |
| **Criptografia** | Refresh token: `secrets.token_urlsafe(48)` (alta entropia, hash SHA-256 sem sal é apropriado pra segredo aleatório, não senha) — JWT HS256 simétrico (backend assina e verifica, sem necessidade de par de chaves) | Adequado ao caso de uso; A3 fechou o único gap real (tamanho mínimo de chave). |
| **Engenharia Reversa / Launcher / Ren'Py** | Repositório inteiro | **Não implementados ainda** — o cliente Tauri (`launcher/`) e o jogo Ren'Py não existem neste repositório nesta fase; a arquitetura (`LIMERENCE_LAUNCHER_ARCHITECTURE.md`) já prevê payload assinado HMAC pra cache offline e o Launcher nunca guardar segredo de longo prazo, mas não há código cliente pra auditar ainda. Fica como pendência explícita pra quando o Launcher for implementado, não como item "ok". |

---

## Testes

Suíte completa: `pytest -q --deselect tests/test_audit_fixes_validation.py`
→ **303 passam**, 1 falha pré-existente sem relação
(`test_help_views.py::test_help_main_view_has_one_button_per_category`, bot
Discord, não tocado nesta fase). `test_audit_fixes_validation.py` (7 testes)
segue exigindo Postgres real + `DISCORD_OAUTH_CLIENT_ID` real — infra
ausente neste ambiente de dev, não é regressão desta auditoria.

Arquivos novos: `tests/test_mercadopago_provider.py`. Arquivos com testes
novos: `tests/test_auth_service.py`, `tests/test_settings.py`,
`tests/test_internal_routes.py` (reescrito pro esquema timestamp+assinatura),
`tests/test_launcher_download_routes.py`.

## Configuração — novidades desta fase

| Env var | Efeito |
|---|---|
| `CORS_ALLOWED_ORIGINS` | lista separada por vírgula; vazio (padrão) = nega toda origem cross-site. |

`JWT_SECRET_KEY` e `INTERNAL_API_SECRET` (quando definido) agora exigem
mínimo de 32 bytes — gere com `openssl rand -base64 32` ou equivalente.
`PUBLIC_BASE_URL` com `ENVIRONMENT=production` agora exige `https://`.
