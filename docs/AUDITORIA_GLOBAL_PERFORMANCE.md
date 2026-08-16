# Auditoria Global de Performance — BOT LIMERENCE (fora do sistema de Tickets)

Data: 2026-08-16
Escopo: auditoria **somente leitura**. Nenhum arquivo de código foi criado, editado ou apagado nesta tarefa — só este relatório.
Método: leitura direta de código + grep, cobrindo tudo fora de `cogs/tickets.py`, `services/ticket_*`, `views/ticket_*`, `services/claim_service.py`, `services/staff_service.py`, `services/log_service.py`, `services/audit_log_service.py` (exceto o achado novo em `get_settings`, abaixo), `services/config_service.py`, `database/database.py` — já cobertos por `docs/AUDITORIA_PERFORMANCE.md`, `docs/AUDITORIA_PERFORMANCE_2.md`, `RELATORIO_DEFER_3S.md`, `docs/BENCHMARK_TICKETS.md`.

Convenção: **CONFIRMADO** = código lido, evidência com arquivo:linha. **SUSPEITA** = padrão que parece problemático mas sem confirmação completa de impacto.

---

## 1. Resumo executivo

1. **`services/automod_service.py:74-76,163-166` + `cogs/automod.py:44`** — `evaluate_message` roda em **toda mensagem de todo servidor** (igual ao bug histórico do `on_message` de tickets, já corrigido) e faz **2 queries sem cache** por mensagem: `get_settings` (nem checa `enabled` antes de consultar o banco) e `list_effective_words` (recarrega a lista de palavras bloqueadas do zero a cada mensagem). É o pior achado desta auditoria — maior escala que o bug de tickets já corrigido, porque roda em canais comuns também, não só em canais de ticket.
2. **`services/audit_log_service.py:36-38` (`get_settings`, sem cache) + `cogs/audit_logs.py:16-18` (`_enabled`)** — chamado incondicionalmente no topo de **18 listeners** (`on_member_ban/unban/remove/update/join`, `on_guild_channel_*`, `on_guild_role_*`, `on_message_delete`, `on_bulk_message_delete`, `on_message_edit`, `on_voice_state_update`, `on_guild_emojis_update`, `on_guild_stickers_update`, `on_guild_update`). `on_message_edit`/`on_message_delete`/`on_voice_state_update` são de alta frequência em servidor ativo — mesmo padrão do achado #1, mas cobrindo muito mais tipos de evento.
3. **`providers/mercadopago.py:81`** — cria um `aiohttp.ClientSession()` novo a cada chamada à API do Mercado Pago (criação de PIX, cancelamento, consulta de status) em vez de reutilizar uma sessão — perde connection pooling/keep-alive, paga handshake TCP+TLS completo em toda chamada ao gateway de pagamento.
4. **`cogs/guild_registry.py:20-26` (`on_ready`)** — itera todas as guilds chamando `ensure_guild` (1-2 round-trips cada) sem guarda contra reexecução. `on_ready` do discord.py dispara **a cada RESUME/reconexão do gateway**, não só no boot — bot com rede instável reprocessa todas as guilds do zero repetidamente.
5. Achados já documentados nas auditorias anteriores (A6/A7 de `AUDITORIA_PERFORMANCE.md`) — **N+1 de settings recarregadas por membro** em `services/booster_service.py` (`reconcile_guild` → `handle_boost_started/removed`) e `services/partnership_service.py` — confirmados **ainda presentes**, não foram corrigidos nas fases 2-4 (que focaram só em tickets).

Nenhum bloqueio síncrono clássico (`time.sleep`, `requests.*`) foi encontrado fora de `venv/` — grep no projeto inteiro confirma que o padrão "só `aiohttp`/`asyncio.to_thread`" continua válido. Nenhum lock/semáforo fora de Tickets encontrado largo demais (todos os já conhecidos — `auth_service.py`, `reconciliation_service.py`, `cogs/verification.py`, `core/rate_limiter.py` — envolvem só operação em memória ou já usam semáforo com limite).

---

## 2. Cogs — achados por cog

### `cogs/automod.py` / `services/automod_service.py` — CONFIRMADO, prioridade mais alta desta auditoria

```python
# cogs/automod.py:41-44
@commands.Cog.listener()
async def on_message(self, message: discord.Message) -> None:
    try:
        await self.bot.automod_service.evaluate_message(message)
```

```python
# services/automod_service.py:74-76
async def get_settings(self, guild_id: int) -> AutoModSettings:
    async with self._database.session() as session:
        return await AutoModSettingsRepository(session).get_or_create(guild_id)
```

```python
# services/automod_service.py:163-166 (list_effective_words)
async def list_effective_words(self, guild_id: int) -> list[EffectiveWord]:
    async with self._database.session() as session:
        overrides = await AutoModWordRepository(session).list_by_guild(guild_id)
```

```python
# services/automod_service.py:227-243 (evaluate_message)
settings = await self.get_settings(message.guild.id)     # query #1, sem cache
if not settings.enabled:
    return
...
words = await self.list_effective_words(message.guild.id)  # query #2, sem cache
```

Roda em toda mensagem não-bot de todo servidor, mesmo quando AutoMod está desativado (a checagem `enabled` só acontece **depois** de já ter pago a query de settings). Nenhum dos dois métodos usa `TTLCache` — ao contrário de `ConfigService`/`StaffService`, que já usam esse padrão. `list_effective_words` monta a lista completa de palavras (builtin + overrides) do zero a cada chamada, incluindo comparação de sets — trabalho de CPU + I/O repetido por mensagem.

Recomendação: aplicar exatamente o mesmo padrão já usado em `ConfigService`/`StaffService` — `TTLCache[int, AutoModSettings]` (ex.: 300s) e `TTLCache[int, list[EffectiveWord]]`, invalidados em `update_settings`/`add_word`/`remove_word`.

### `cogs/audit_logs.py` — CONFIRMADO

```python
# cogs/audit_logs.py:16-18
async def _enabled(self, guild_id: int, category: AuditLogCategory) -> bool:
    settings = await self.bot.audit_log_service.get_settings(guild_id)
    return bool(getattr(settings, category.value))
```

```python
# services/audit_log_service.py:36-38
async def get_settings(self, guild_id: int) -> AuditLogSettings:
    async with self._database.session() as session:
        return await AuditLogSettingsRepository(session).get_or_create(guild_id)
```

`_enabled` é chamado como primeira linha em 18 listeners do arquivo (`grep -n "async def on_"` retorna 18 handlers, todos chamam `_enabled` antes de qualquer outra coisa) — nenhum tem cache. Os mais frequentes em servidor ativo: `on_message_edit:388`, `on_message_delete:341`, `on_voice_state_update` (linha 408, entra/sai de call). Isso é uma query de banco por edição/exclusão de mensagem e por troca de estado de voz, em todo servidor, independentemente de a categoria estar habilitada ou não.

Recomendação: mesmo padrão — `TTLCache[int, AuditLogSettings]` em `AuditLogService.get_settings`, invalidado em `update_settings`/`reset_settings`. `AuditLogService` já tem um cache próprio (`_lookup_cache` para `resolve_executor`, linha 32) — o precedente de cache já existe na própria classe, só falta aplicar em `get_settings`.

### `cogs/antispam.py` — sem achados

`on_message` (linha 63) já usa `config_service.get_settings`/`get_anti_spam_settings`, ambos cacheados (confirmado em `services/config_service.py`). Estruturas em memória (`_buffers`, `_last_reported`) têm sweep periódico contra vazamento (linhas 26-36, 148-160) — já revisado e aprovado na auditoria anterior.

### `cogs/guild_registry.py` — CONFIRMADO (menor)

```python
# cogs/guild_registry.py:20-26
@commands.Cog.listener()
async def on_ready(self) -> None:
    for guild in self.bot.guilds:
        try:
            await self.bot.guild_service.ensure_guild(guild)
```

`GuildService.ensure_guild` (`services/guild_service.py:20-24`) faz `get_or_create` + `session.refresh` — 1-2 round-trips por guild. `on_ready` do discord.py dispara toda vez que o gateway reconecta/resume (não é exclusivo do boot frio) — em uma rede instável isso reprocessa todas as guilds do zero repetidamente, sem nenhuma guarda ("já rodei isso desde que conectei"). Baixo/médio impacto (poucas guilds hoje, ver Fase 3 de `AUDITORIA_PERFORMANCE.md`), mas cresce com o número de guilds e frequência de reconexão.

Recomendação: guardar um `bool`/`set` de guilds já sincronizadas nesta sessão de conexão, ou mover para `on_guild_available`/checar só guilds novas.

### `cogs/invites.py` — sem achados

`on_invite_create` usa `get_permission_settings`/`get_settings`, ambos cacheados; evento raro (criação de convite).

### `cogs/shop.py` — CONFIRMADO (N+1 leve, já observado como "risco" em `RELATORIO_DEFER_3S.md`, aqui detalhado)

```python
# cogs/shop.py:43-53
plans = await self.bot.plan_service.list_plans(interaction.guild_id, only_active=True)
...
for plan in plans:
    benefits = await self.bot.plan_service.list_benefits(plan.id)   # 1 query por plano
    benefits_by_plan[plan.id] = [b.text for b in benefits]
```

N+1 clássico: 1 query por plano ativo em vez de 1 query batelada (`WHERE plan_id IN (...)`). Comando `/loja`, não crítico em frequência, mas cresce com número de planos.

### `cogs/moderation.py`, `cogs/verification.py`, `cogs/boosters.py`, `cogs/painel.py`, `cogs/bot_status.py`, `cogs/subscription_renewal.py`, `cogs/partnership.py`, `cogs/polls.py`, `cogs/giveaways.py`, `cogs/reminders.py`, `cogs/payment_expiration.py`, `cogs/backup.py`, `cogs/inactivity.py`, `cogs/license_reconciliation.py`, `cogs/status.py`, `cogs/staff.py`, `cogs/help.py`, `cogs/ranking.py`, `cogs/claim.py`, `cogs/audit.py`, `cogs/config.py` — sem achados novos

Tabela de tasks (frequência, iteração de guilds, concorrência) já coberta em `AUDITORIA_PERFORMANCE.md` seção "Tasks" — confirmado sem mudança estrutural (mesmo conjunto de `@tasks.loop`, mesmos padrões de `before_loop`/`cog_unload`, nenhuma task nova, nenhum sinal de duplicação por reload). `cogs/moderation.py` `on_message` (linha 195) só processa DMs (`message.guild is not None: return`), custo desprezível.

---

## 3. Services fora de Tickets — achados por service

### `services/booster_service.py` — CONFIRMADO (ainda presente, já documentado como A7 em `AUDITORIA_PERFORMANCE.md`, não foi corrigido)

```python
# services/booster_service.py:56-58 (sem cache)
async def get_settings(self, guild_id: int) -> BoosterSettings:
    async with self._database.session() as session:
        return await BoosterSettingsRepository(session).get_or_create(guild_id)
```

```python
# services/booster_service.py:78-114 (reconcile_guild)
settings = await self.get_settings(guild.id)          # já busca 1x
...
for user_id in tracked_ids - actually_boosting_ids:
    ...
    await self.handle_boost_removed(member)            # rebusca settings dentro (linha 170)
for member in guild.premium_subscribers:
    if member.id not in tracked_ids:
        await self.handle_boost_started(member)         # rebusca settings dentro (linha 119)
```

`reconcile_guild` já carrega `settings` uma vez, mas cada `handle_boost_started`/`handle_boost_removed` chamado dentro do loop rebusca via `self.get_settings` de novo — 1 query redundante por membro divergente. Cron de 1h (`cogs/boosters.py:39`), baixo volume típico, mas seria eliminado de graça se `get_settings` virasse cache TTL (mesmo padrão do resto do projeto) em vez de precisar mudar as assinaturas dos handlers.

### `services/partnership_service.py` — CONFIRMADO (mesmo padrão, A6/A7-like, não corrigido)

`get_settings` (linha 92-95) sem cache; `reconcile_guild` (linha 176+) e `handle_role_gained`/`handle_role_lost` (linhas 120, 154) idem — mesmo formato do booster. Cron de 1h.

### `services/subscription_reminder_service.py` — CONFIRMADO parcialmente corrigido, N+1 residual ainda presente

`run_check_cycle` (linha 88-116) já carrega `settings`, `subscriptions`, `plans` e `reminder_days` **uma vez por guild**, fora do loop — a parte "hoisting de settings" do achado A6 antigo **já está corrigida**. O que resta, por assinatura processada dentro do loop (`_process_subscription` → `_maybe_send_day_reminders`):

```python
# services/subscription_reminder_service.py:189-200
reminder_id = await self._reserve_reminder(subscription, reminder_type, period_end, now)  # sessão própria
...
delivery = await self._send(...)                                                          # sessão própria (template/botões)
await self._finalize_reminder(reminder_id, delivery_status=delivery.status)                # sessão própria
await self._audit(...)                                                                     # sessão própria
```

`grep "self._database.session()"` no arquivo mostra ~9 pontos de abertura de sessão espalhados entre `_reserve_reminder` (347), `_finalize_reminder` (357), `_send` (370+) e `_audit` (456+) — 3-5 round-trips por assinatura por ciclo, cron de 15 min. Ganho residual menor que o A6 original (que já foi parcialmente resolvido), mas ainda escala linear com nº de assinaturas ativas.

### `services/verification_service.py` — CONFIRMADO (N+1 novo, não estava nos achados anteriores)

```python
# services/verification_service.py:570-597 (sweep_expired, cron 1 min, global)
async with self._database.session() as session:
    expired = await VerificationSessionRepository(session).list_expired_pending(now)
    ids = [record.id for record in expired]

for session_id in ids:
    async with self._database.session() as session:
        repo = VerificationSessionRepository(session)
        record = await repo.get_by_id_locked(session_id)
        ...
        settings = await VerificationSettingsRepository(session).get_or_create(record.guild_id)  # 1x por SESSÃO, não por guild
    action = VerificationExceededAction(settings.on_expire_action)
    await self._finalize(record, settings, action, result_label="Expirado")
```

`VerificationSettingsRepository.get_or_create(record.guild_id)` é chamado **por sessão expirada**, não uma vez por guild — se várias sessões da mesma guild expiram no mesmo tick, as settings da guild são recarregadas repetidamente. Volume tipicamente baixo (poucas verificações expirando por minuto), mas é o mesmo padrão de desperdício documentado em outros services.

### `services/punishment_review_service.py` / `cogs/moderation.py` — CONFIRMADO (N+1 novo)

```python
# services/punishment_review_service.py:90-98 (list_pending — usado por /analises)
async with self._database.session() as session:
    punishments = await PunishmentRepository(session).list_pending_review(guild_id, types=types, staff_id=staff_id)
items: list[PendingPunishmentItem] = []
for punishment in punishments:
    appeal = await self._punishment_service.get_pending_appeal(punishment.id)   # 1 query por punição
    items.append(PendingPunishmentItem(punishment=punishment, appeal=appeal))
```

```python
# cogs/moderation.py:89-99 (review_expiration_task, cron 1 min, global)
for punishment in await self.bot.punishment_service.list_expired_pending_reviews():
    ...
    pending_appeal = await self.bot.punishment_service.get_pending_appeal(punishment.id)  # 1 query por punição
```

`get_pending_appeal` é chamado por item em vez de uma query batelada (`WHERE punishment_id IN (...)`) — presente tanto no comando `/analises` (sob demanda, staff) quanto no cron de expiração automática (1 min, todas as guilds). Volume normalmente pequeno (nº de punições pendentes de análise raramente é grande), prioridade baixa-média.

### `services/giveaway_service.py` — CONFIRMADO (já documentado como M7/N+1 baixa prioridade em `AUDITORIA_PERFORMANCE.md`, ainda presente)

```python
# services/giveaway_service.py:172,180,199,204 (close_and_draw / reroll)
for user_id in winners:
    await self._award_prize(giveaway, user_id)   # insert por vencedor, sessão própria
```

Sem mudança desde a auditoria anterior — volume pequeno (nº de vencedores por sorteio), continua baixa prioridade.

### `services/role_sync_service.py` — sem achados relevantes

`handle_license_event`/`handle_player_verified` fazem 1 query em lote (`PlanRepository.list_by_product`, `GuildSettingsRepository.list_with_verified_role`) antes do loop, e o loop em si só faz chamadas Discord (`fetch_member`/`add_roles`), não queries de banco por item. `EventBus.publish` (`core/event_bus.py:27-36`) despacha handlers sequencialmente com `try/except` isolado por handler — nenhum handler síncrono pesado encontrado.

### `services/api/routes/player_routes.py` — CONFIRMADO (já documentado como baixa-média em `AUDITORIA_PERFORMANCE.md`, ainda presente)

```python
# api/routes/player_routes.py:36-37
for lic in license_rows:
    product = await product_service.get(lic.product_id, include_deleted=True)  # 1 query por licença
```

Sem mudança desde a auditoria anterior.

### `services/ranking_service.py`, `services/license_service.py`, `services/coupon_service.py`, `services/plan_service.py`, `services/product_service.py`, `services/payment_service.py`, `services/evaluation_service.py`, `services/help_service.py`, `services/vote_weight_service.py`, `services/guild_service.py`, `services/bot_status_service.py`, `services/subscription_renewal_config_service.py`, `services/poll_service.py` (exceto o já citado), `services/punishment_service.py`, `services/reconciliation_service.py` — sem achados

`ranking_service.py` usa queries agregadas em lote (`GROUP BY`) em vez de loop — bom padrão, nenhum N+1. `reconciliation_service.py` — semáforo (`asyncio.Semaphore(max_concurrency)`) e timeout por guild confirmados presentes (`services/reconciliation_service.py:81,94`), conforme já implementado na Fase 4 de `AUDITORIA_PERFORMANCE.md`; nenhuma regressão. Demais services sem loop com query por item.

---

## 4. Tasks / background jobs — achados

Conjunto de `@tasks.loop` idêntico ao já catalogado em `AUDITORIA_PERFORMANCE.md` (15 tasks, mesmos arquivos/intervalos) — confirmado via grep, nenhuma task nova, nenhum removido. Todas seguem `before_loop -> wait_until_ready()` e `cog_unload -> task.cancel()`; carregamento único via `pkgutil` (sem risco de duplicação por reload).

Achados novos desta auditoria dentro de tasks já existentes:
- `services/verification_service.py:sweep_expired` (chamada por `cogs/verification.py:54`, 1 min) — N+1 de settings por sessão expirada (seção 3).
- `cogs/moderation.py:review_expiration_task` (1 min) — N+1 de `get_pending_appeal` por punição expirada (seção 3).
- `cogs/guild_registry.py:on_ready` — não é `@tasks.loop`, mas é um listener que reprocessa todas as guilds a cada reconexão do gateway (seção 2).

Nenhuma task nova identifica risco de concorrência não controlada além do já documentado (`reconcile_licenses` com semáforo interno; `announcement_tick` sem pré-filtro, já registrado como M11 em `AUDITORIA_PERFORMANCE.md`, ainda presente — confirmado por leitura de `cogs/partnership.py`, sem mudança).

---

## 5. api/ e providers/ — achados

### `providers/mercadopago.py` — CONFIRMADO

```python
# providers/mercadopago.py:76-95 (_request, chamado por create_payment/cancel_payment/get_payment/create_subscription/cancel_subscription)
async def _request(self, method, path, *, json=None, idempotency_key=None):
    url = f"{_BASE_URL}{path}"
    try:
        async with aiohttp.ClientSession(timeout=_REQUEST_TIMEOUT) as session:
            async with session.request(method, url, json=json, headers=self._headers(...)) as response:
                ...
```

Cria uma `aiohttp.ClientSession()` nova a cada chamada HTTP ao Mercado Pago, em vez de manter uma sessão de vida longa reutilizada entre chamadas (padrão recomendado pela própria documentação do aiohttp — reaproveita pool de conexões TCP/TLS). Toda criação de PIX, cancelamento e consulta de status (usado tanto no fluxo de compra quanto na reconciliação de pagamentos) paga handshake completo. Timeout (15s) e tratamento de erro já estão corretos — só falta reuso de sessão.

Recomendação: instanciar `aiohttp.ClientSession` uma vez no `__init__`/`setup_hook` do provider (ou usar um `TCPConnector` compartilhado) e reutilizar, fechando só no shutdown do bot.

### `services/auth_service.py:317` — SUSPEITA (baixa prioridade)

Mesmo padrão (`aiohttp.ClientSession()` por chamada) na troca de código OAuth do Discord (`_exchange_and_fetch_discord_user`), mas esse caminho só roda por login de usuário no launcher — frequência muito menor que pagamentos. Baixo impacto, mesma classe de problema.

### `api/routes/internal_routes.py` — sem achados novos

`/internal/reconcile` continua síncrono por decisão explícita já documentada e testada na Fase 4 de `AUDITORIA_PERFORMANCE.md` (semáforo + timeout por guild já aplicados em `reconciliation_service.py`); `/internal/license-events` e `/internal/player-verified` despacham direto para `role_sync_service`, sem trabalho pesado no handler HTTP.

### `api/routes/player_routes.py` — ver seção 3 (N+1 já documentado, confirmado ainda presente).

### `api/routes/launcher_routes.py`, `api/routes/download_routes.py`, `api/routes/auth_routes.py`, `api/routes/webhook_routes.py`, `api/routes/health_routes.py` — sem achados

`launcher_routes.py` já usa paginação (`Query(..., le=100)`); `download_routes.py`/`auth_routes.py` não têm loop nem I/O síncrono; assinatura de webhook (`mercadopago.py:validate_webhook`) é cálculo local (HMAC), sem custo de rede.

### `providers/storage/s3_compatible.py`, `providers/manual.py`, `providers/base.py` — sem achados novos

`generate_presigned_url` (já observado como baixo em `AUDITORIA_PERFORMANCE.md`) continua sendo cálculo local, sem I/O de rede.

---

## 6. Locks/concorrência fora de Tickets

| Lock | Arquivo:linha | Escopo | Avaliação |
|---|---|---|---|
| `asyncio.Lock()` | `services/auth_service.py:110` | Protege só dicts em memória (`_pending_logins`, `_state_to_device_code`) — nunca envolve sessão de DB nem chamada HTTP (`_exchange_and_fetch_discord_user`, linha 312, roda **fora** do lock, linhas 220-241 confirmam que o lock é liberado antes da chamada de rede) | Correto, escopo estreito, sem achado |
| `asyncio.Lock()` | `services/reconciliation_service.py:81` | Serializa disparo periódico vs. sob demanda de `reconcile_all_guilds` | Já documentado/testado na Fase 4 anterior, sem mudança |
| `asyncio.Semaphore(max_concurrency)` | `services/reconciliation_service.py:94` | Limita concorrência entre guilds dentro de `reconcile_all_guilds` | Confirmado presente, default 5 (configurável via env) |
| `asyncio.Semaphore(_MAX_CONCURRENT_JOINS)` | `cogs/verification.py:32` | Limita `on_member_join` concorrentes | Confirmado presente, sem achado novo |
| `asyncio.Lock()` | `core/rate_limiter.py:38` | Protege estruturas internas do rate limiter | Confirmado presente, sem achado novo |

Nenhum lock encontrado fora de Tickets serializa mais do que o necessário — todos ou protegem só estado em memória local, ou já têm limite de concorrência explícito.

---

## 7. Chamadas síncronas bloqueantes (grep global)

```
grep -rn "time\.sleep\|requests\.get\|requests\.post\|requests\.put\|requests\.delete\|requests\.request" \
  --include="*.py" cogs services api providers core utils database main.py config
```

Resultado: **vazio** — nenhuma ocorrência fora de `venv/` (as ocorrências em `venv/Lib/site-packages/...` são bibliotecas de terceiros, fora do escopo do projeto). Confirma o achado já registrado em `AUDITORIA_PERFORMANCE.md`: o projeto não usa `requests`/`time.sleep`/chamada HTTP síncrona em lugar nenhum do código próprio — só `aiohttp` (assíncrono).

`utils/` inteiro revisado (`dashboard_chart.py`, `transcript.py`, `pix_payload.py`, `pix_validation.py`, `formatter.py`, `achievements.py`, `time.py`, `ticket_lifecycle.py`, `ttl_cache.py`, `timing.py`, `checks.py`, `constants.py`, `automod_wordlist.py`, `appeal_dm.py`, `model_defaults.py`) — nenhum I/O de arquivo/zip fora de `transcript.py` (já confirmado usando `asyncio.to_thread` em auditoria anterior, não reconferido em detalhe conforme instrução).

---

## 8. Startup

`core/bot.py:__init__` (linhas 72-116) — instancia todos os services em sequência, sem I/O (só construtores, nenhum `await`) — custo desprezível, O(1) em nº de guilds.

`core/bot.py:setup_hook` (linhas 140-161):
- `await self.database.check_connection()` — 1 round-trip, necessário.
- `await self._load_cogs()` — carregamento de módulos, sem I/O de rede pesado.
- `await self._register_persistent_views()` — registra views/dynamic items (síncrono em memória) + `ticket_panel_service.register_published_views()`/`register_published_groups()` (já fora do escopo desta auditoria, ligado a Tickets).
- **`tree.sync()` incondicional confirmado ainda presente** (`core/bot.py:148,152,158`) — mesmo achado M8 de `AUDITORIA_PERFORMANCE.md`, não corrigido nas fases seguintes (que também não pretendiam corrigi-lo, conforme `AUDITORIA_PERFORMANCE_2.md` seção 7.6, "fora do caminho crítico de latência por clique").
- Nenhuma chamada HTTP externa bloqueante antes de `bot.start()`.

`cogs/guild_registry.py:on_ready` (fora de `setup_hook`, mas efetivamente parte do fluxo de "ficar operacional") — ver seção 2, reprocessa todas as guilds a cada reconexão do gateway, não só no boot frio.

Nenhum outro trabalho pesado encontrado entre o boot e o bot ficar operacional.

---

## 9. Recomendações priorizadas

| # | Achado | Arquivo | Impacto estimado | Esforço |
|---|---|---|---|---|
| 1 | Cache de `AutoModSettings`/`list_effective_words` (mesmo padrão TTLCache já usado em `ConfigService`) | `services/automod_service.py:74-76,163-166` | **Alto** — elimina 2 queries por mensagem em todo servidor, mesmo com AutoMod desligado | Baixo (mecânico, mesmo padrão já existente no projeto) |
| 2 | Cache de `AuditLogSettings` (`get_settings`) | `services/audit_log_service.py:36-38` | **Alto** — elimina 1 query por evento de auditoria (edição/exclusão de mensagem, voz, etc.) em 18 listeners | Baixo (mesmo padrão) |
| 3 | Reutilizar `aiohttp.ClientSession` no `MercadoPagoProvider` em vez de criar uma por chamada | `providers/mercadopago.py:81` | Médio — reduz latência de toda chamada ao gateway de pagamento (handshake TCP/TLS evitado) | Baixo-médio (gerenciar ciclo de vida da sessão) |
| 4 | Cache de `BoosterSettings`/`PartnershipSettings` (elimina rebusca por membro divergente em `reconcile_guild`) | `services/booster_service.py:56-58`, `services/partnership_service.py:92-95` | Médio — cron de 1h, mas cresce com nº de membros divergentes | Baixo (mesmo padrão) |
| 5 | Guarda de reexecução em `on_ready` (não reprocessar todas as guilds a cada reconexão do gateway) | `cogs/guild_registry.py:20-26` | Baixo-médio — cresce com nº de guilds × frequência de reconexão | Baixo |
| 6 | Batelar `get_pending_appeal` por lista de punições em vez de 1 query por item | `services/punishment_review_service.py:90-98`, `cogs/moderation.py:89-99` | Baixo — volume tipicamente pequeno | Médio (mudar assinatura do repositório para `IN (...)`) |
| 7 | Batelar settings de verificação por guild (não por sessão expirada) no sweep | `services/verification_service.py:570-597` | Baixo | Baixo |
| 8 | Batelar `list_benefits` por lista de planos em `/loja` | `cogs/shop.py:43-53` | Baixo | Baixo |
| 9 | Reduzir round-trips residuais em `subscription_reminder_service` (reserva/finalização/auditoria por assinatura) | `services/subscription_reminder_service.py:189-200` | Baixo-médio — cron de 15 min, escala com nº de assinaturas ativas | Médio (mexe em fluxo de idempotência de lembrete, já sinalizado como sensível na auditoria anterior) |
| 10 | Batelar `product_service.get()` por licença | `api/routes/player_routes.py:36-37` | Baixo | Baixo |
| 11 | Reuso de sessão HTTP em `auth_service._exchange_and_fetch_discord_user` | `services/auth_service.py:317` | Muito baixo (fluxo de login, baixa frequência) | Baixo |
| 12 | (já conhecido, não corrigido) `tree.sync()` incondicional no boot | `core/bot.py:148,152,158` | Médio — só em deploys frequentes | Médio (precisa de hash/diff confiável) |

Nenhuma recomendação acima foi aplicada — são candidatas para uma fase de implementação futura, seguindo o mesmo método (grep de chamadores reais antes de decidir) já usado nas fases anteriores.

---

## 10. Confirmação

Nenhum arquivo de código foi alterado nesta auditoria — só este relatório novo (`docs/AUDITORIA_GLOBAL_PERFORMANCE.md`) foi criado. Esta tarefa rodou 100% em modo leitura (`Read`/`Grep`/`Bash` só de consulta) — nenhum `Edit`/`Write` foi feito em nenhum arquivo além deste relatório, nenhum `git commit`/`reset`/`checkout`/`restore`/`clean` foi executado, nenhum `pip install` nem alteração de venv.

```
$ git status --short
 M cogs/tickets.py
 M config/settings.py
 M core/bot.py
 M database/database.py
 M database/models/partnership.py
 M database/models/payment.py
 M database/models/punishment.py
 M database/models/subscription.py
 M database/models/ticket.py
 M database/models/ticket_settings.py
 M database/models/verification_session.py
 M database/repositories/discount_coupon_repository.py
 M services/audit_log_service.py
 M services/claim_service.py
 M services/config_service.py
 M services/config_transfer_service.py
 M services/log_service.py
 M services/reconciliation_service.py
 M services/staff_service.py
 M services/ticket_panel_service.py
 M services/ticket_service.py
 M tests/test_audit_fixes_validation.py
 M tests/test_reconciliation_service.py
 M views/embeds.py
 M views/painel_view.py
 M views/ticket_actions_view.py
 M views/ticket_closed_view.py
 M views/ticket_panel_open_view.py
 M views/ticket_panels_view.py
?? CLAUDE_PROMPT.txt
?? RELATORIO_DEFER_3S.md
?? alembic/versions/15cdb4300d1a_indices_compostos_hot_paths.py
?? alembic/versions/a7e3f1b9c4d2_metodo_de_selecao_de_categorias.py
?? docs/AUDITORIA_GLOBAL_PERFORMANCE.md
?? docs/AUDITORIA_PERFORMANCE.md
?? docs/AUDITORIA_PERFORMANCE_2.md
?? docs/BENCHMARK_TICKETS.md
?? tests/test_database_engine_config.py
?? tests/test_perf_audit_2.py
?? tests/test_ticket_actions_optimizations.py
?? tests/test_ticket_panel_redesign.py
?? utils/timing.py
```

Nota: a lista de `M`/`??` acima é maior do que o snapshot registrado no início desta sessão (`gitStatus` do contexto inicial) — isso reflete trabalho paralelo em outra sessão/processo tocando o repositório enquanto esta auditoria rodava (mesmo fenômeno já registrado em `docs/AUDITORIA_PERFORMANCE_2.md`, que roda "durante esta sessão eles continuaram sendo modificados por outro trabalho em paralelo"). Nenhum desses arquivos foi tocado por esta tarefa — a única entrada nova atribuível a esta auditoria é `docs/AUDITORIA_GLOBAL_PERFORMANCE.md`.
