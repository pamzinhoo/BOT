# Auditoria de Performance — BOT LIMERENCE

Data: 2026-08-11
Escopo: auditoria completa, somente leitura. Nenhuma alteração de código foi feita nesta etapa.
Metodologia: 5 varreduras paralelas cobrindo arquitetura/código morto, event loop/tasks, banco de dados/N+1/transações, API Discord/memória/cache, FastAPI/startup/comandos/logging. Achados verificados por grep/leitura direta do código (não é opinião estática de linter isolado).

---

## Resumo executivo

Codebase em geral **bem disciplinado** para um bot deste porte: já existe `asyncio.to_thread` para matplotlib/xhtml2pdf/zip, teste de regressão anti-blocking-loop, cache TTL com invalidação para settings, semáforo em `on_member_join`, lock em reconciliação de licenças, sweep de rate-limiters, `add_done_callback` em background tasks. Não é um projeto "bagunçado" — os problemas encontrados são pontuais, não sistêmicos.

Achados sérios:
- **1 bug de correção de dados** (não é só performance) em cupom de desconto — loop de INSERT duplicado.
- **Nenhum bloqueio real de event loop** foi confirmado (sem `requests`/`time.sleep`/`subprocess` síncrono). O maior risco de "travar" o bot é a rota `/internal/reconcile`, que faz uma cadeia longa de awaits sequenciais compartilhando o mesmo rate limiter HTTP do Discord.
- **Falta de índices compostos** em tabelas que crescem sem limite (punishments, subscriptions, payment_history) filtradas só por `status` em sweeps periódicos — vira table scan que piora com o tempo.
- **N+1 sistemático** em 3 serviços de reconciliação/lembrete (settings recarregadas por membro/assinatura dentro do loop, em vez de uma vez por guild).
- **Concorrência não limitada** em `ReconciliationService.reconcile_all_guilds` — único loop cross-guild que usa `asyncio.gather` sem semáforo, gerando rajada simultânea contra DB e Discord (todo o resto do código itera guild por guild sequencialmente, de propósito).
- **1 query por mensagem, em todo servidor**, só para checar se o canal é um ticket (`cogs/tickets.py` `on_message`).
- Migrations Alembic com **3 heads não mesclados** — `alembic upgrade head` quebra até rodar merge.
- Código morto é escasso e majoritariamente de baixo risco (helpers/repos sem chamador), mas há 2-3 itens que merecem investigação antes de remover (podem indicar lacuna funcional, não código morto de verdade).

Nenhuma violação de segurança, isolamento de guild ou atomicidade de pagamento foi encontrada além do bug do cupom.

---

## Críticos

| # | Arquivo:Linha | Problema | Impacto | Solução recomendada | Risco da alteração | Ganho estimado |
|---|---|---|---|---|---|---|
| C1 | `database/repositories/discount_coupon_repository.py:75-84` (`DiscountCouponPlanRepository.replace_for_coupon`) | Loop de insert + flush duplicado verbatim (linhas 79-81 e 82-84 idênticas) — insere o mesmo par `(coupon_id, plan_id)` duas vezes, violando `UniqueConstraint("coupon_id","plan_id")`. Chamado em `services/coupon_service.py:299,332,361` (edição/clonagem de cupom). | Qualquer edição de cupom com lista de planos não-vazia deveria estar lançando `IntegrityError` hoje. Se não está travando em produção, algo está engolindo o erro — o que seria um bug adicional. Path de monetização. | Remover o segundo loop (manter só um `for` + um `flush()`). | Baixo — é reversão de uma duplicação acidental, não muda semântica pretendida. | Corrige bug funcional; não é otimização de performance, é correção. |

---

## Altos

| # | Arquivo:Linha | Problema | Impacto | Severidade | Solução recomendada | Risco | Ganho estimado |
|---|---|---|---|---|---|---|---|
| A1 | `services/reconciliation_service.py:64-67` (`reconcile_all_guilds`) | Único loop cross-guild do projeto usando `asyncio.gather(*(reconcile_guild(g) for g in bot.guilds))` sem limite de concorrência — roda 1x/hora e também sob demanda via `POST /internal/reconcile`. Todo o resto do código itera guild por guild sequencialmente de propósito. | Rajada simultânea de queries + `add_roles`/`remove_roles` contra centenas de guilds ao mesmo tempo — pressão no pool de conexões DB e no rate limiter HTTP do Discord (compartilhado com o gateway do bot). | ALTO | Adicionar `asyncio.Semaphore(N)` limitando guilds processadas em paralelo, ou reverter para sequencial/lotes como os outros loops cross-guild já fazem. | Baixo — muda só a forma de agendamento, não a lógica de reconciliação (lock já existe para evitar reentrância). | Reduz picos de latência/rate-limit em contas com muitas guilds. |
| A2 | `api/routes/internal_routes.py:68-86` (`POST /internal/reconcile`) | Chama `reconcile_all_guilds()` inline no handler HTTP — não bloqueia o loop tecnicamente (é tudo `await`), mas pode segurar a vez de execução do loop por dezenas de segundos a minutos em instalação multi-guild, competindo com heartbeat/dispatch do gateway Discord (mesmo processo/loop, ver `main.py`). | Se coincidir com atividade do bot, aumenta latência percebida em comandos/gateway durante a reconciliação. | ALTO | Disparar como `BackgroundTasks`/fire-and-forget, retornar `202 Accepted` imediatamente; relatório consultado separadamente. | Baixo-médio — muda contrato da resposta HTTP (síncrono → assíncrono), precisa avisar consumidor do endpoint (backend interno). | Bot deixa de ter latência afetada por reconciliação sob demanda. |
| A3 | `database/repositories/punishment_repository.py:94-135`, `subscription_repository.py:87-95`, `payment_repository.py:14-22` | Queries de sweep (cron) filtram só por `status` (+ coluna de data), sem filtro de `guild_id`, e a coluna `status` não tem índice em nenhuma das 3 tabelas. | Table scan completo a cada tick de scheduler (moderation review, renovação de assinatura, expiração de pagamento). Tabelas só crescem — piora com o tempo, nunca encolhe. | ALTO | Índices compostos/parciais: `(status, review_deadline_at) WHERE status='pending_review'` em punishments; `(status, expires_at) WHERE status='active'` idem; `(status, current_period_end) WHERE status='active'` em subscriptions; `(status, expires_at) WHERE status='pending'` em payment_history. | Baixo — migration Alembic aditiva, sem mudança de comportamento. | Alto conforme tabelas crescem; sweep passa de scan completo para index scan. |
| A4 | `database/repositories/*_repository.py` (punishment, subscription, payment_history) | Filtro comum `WHERE guild_id = X AND user_id = Y [AND status]` só tem índices single-column separados — Postgres faz bitmap-AND em vez de index scan único. | Consultas de hot-path (abrir painel de ticket, checar assinatura ativa, listar pagamentos de usuário) ficam mais caras conforme tabela cresce. | ALTO | Índices compostos `(guild_id, user_id)` nas 3 tabelas. | Baixo — migration aditiva. | Médio-alto, cresce com volume de dados. |
| A5 | `database/repositories/ticket_repository.py:29-37` (`count_open_by_member`) | Filtra `guild_id + opened_by_discord_id + status IN(...)` no caminho quente de criação de ticket (checagem de limite); `opened_by_discord_id` sem índice. | Toda abertura de ticket paga esse custo. | ALTO (hot path, alta frequência) | Índice composto `(guild_id, opened_by_discord_id, status)` ou ao menos `(guild_id, opened_by_discord_id)`. | Baixo. | Direto — comando muito usado. |
| A6 | `services/subscription_reminder_service.py:99-360` | N+1: para cada assinatura, reabre sessões separadas para reservar lembrete, finalizar, auditar, buscar template de mensagem e buscar botões — 4 a 6 round-trips de DB **por assinatura**, a cada tick do scheduler. `list_buttons` ainda faz SELECT + possíveis INSERTs de botões padrão a cada chamada. | Escala linear com nº de assinaturas ativas, roda periodicamente. | ALTO | Buscar settings/dias de lembrete/botões/templates uma vez por guild por ciclo (fora do loop); avaliar se o padrão de commits separados é ledger de idempotência proposital antes de agrupar (ver seção Transações). | Médio — envolve fluxo de assinatura/renovação, exige confirmar se separação de sessões é proposital (parece ser, como "livro-razão" de idempotência). | Alto em contas com muitas assinaturas. |
| A7 | `services/booster_service.py:97-199`, `services/partnership_service.py:120-206` | Mesmo padrão N+1: `reconcile_guild` já busca settings/config uma vez, mas os handlers por membro (`handle_boost_removed/started`, `handle_role_gained/lost`) rebuscam settings e abrem sessão própria por membro divergente. | 2x round-trips por membro divergente em vez de 1x por guild. | ALTO | Passar settings já buscadas como parâmetro para os handlers; batch-load registros de Booster/Partnership por lista de user_ids em vez de um por vez. | Baixo-médio — mudança de assinatura de função interna, sem mudar comportamento externo. | Médio-alto em guilds com muitos boosters/parceiros. |
| A8 | `cogs/tickets.py:14-21` (`on_message`) | Roda em **toda mensagem não-bot de todo servidor**, faz `get_by_channel_id` para checar se o canal é ticket; se for, `record_first_message` reconsulta `get_by_channel_id` de novo (segunda vez, redundante). | Query de banco por mensagem de chat, em todo servidor, mesmo fora de canais de ticket. | ALTO | Cache "canais de ticket conhecidos" por guild com TTL curto (mesmo padrão já usado em `ConfigService`), em vez de query por mensagem. | Baixo-médio — precisa estratégia de invalidação ao abrir/fechar ticket. | Alto em servidores com chat volumoso. |
| A9 | `alembic/versions/` | Cadeia de migrations com **3 heads não mesclados**: `9f1c7d2a5b4e`, `7d3a9e1c4f68`, `e1a9c4f7b3d2`. | `alembic upgrade head` falha até rodar merge — bloqueia qualquer deploy que dependa de aplicar migrations novas. | ALTO (bloqueador operacional) | Rodar `alembic merge` unindo os 3 heads em uma migration de merge. | Baixo — merge não muda schema, só a árvore de histórico. | Desbloqueia pipeline de migration. |

---

## Médios

| # | Arquivo:Linha | Problema | Severidade | Solução | Risco |
|---|---|---|---|---|---|
| M1 | `cogs/backup.py:149-185` (`_dump_database/_dump_config/_dump_ranking/_dump_dashboard`) | `Path.write_text(json.dumps(...))` síncrono dentro de método `async`, ao contrário de `_copy_transcripts/_zip_dir` (mesmo arquivo) que já foram movidos para `asyncio.to_thread`. Roda 1x/dia por guild. | MEDIO | Envolver em `asyncio.to_thread`, mesmo padrão já usado ao lado. | Baixo — mecânico. |
| M2 | `cogs/inactivity.py:73,82,107` | `_last_message_at` chamado 2x por ticket aberto a cada 5 min, cada chamada faz `channel.history(limit=200)` separado (uma para "última mensagem", outra para "última mensagem do dono"). | MEDIO | Percorrer o histórico uma vez só, rastreando os dois valores no mesmo loop. | Baixo. |
| M3 | `services/painel_service.py` `refresh_dashboard` (~15 call sites) | Cada chamada dispara task de background independente com seu próprio `fetch_message`+`edit`, sem debounce/coalescing. Ações em rajada (várias ações de ticket seguidas) podem gerar edits concorrentes na mesma mensagem. | MEDIO | Debounce/coalescer edits na mesma mensagem dentro de uma janela curta. | Médio — precisa preservar "última atualização vence". |
| M4 | `database/models/subscription.py:37`, `payment.py:44`, `punishment.py:53` | Índices de `user_id` existem no banco (via migration raw) mas não estão declarados no model (`index=True`) — drift entre schema real e metadata do SQLAlchemy. | MEDIO | Adicionar `index=True` nos models correspondentes. | Baixo. |
| M5 | `database/models/ticket.py` (`claimed_by_staff_id`) | Usado em WHERE (`list_by_staff`, `most_common_category_for_staff`) mas sem índice. | MEDIO | Adicionar `index=True`. | Baixo. |
| M6 | `database/repositories/guild_settings_repository.py` e outros `get_or_create` (booster/partnership/subscription-renewal settings) | Padrão SELECT-depois-INSERT em vez de upsert atômico; sem cache TTL (ao contrário de `config_service.py` que já tem). | MEDIO | Estender `TTLCache` (já existe em `utils/ttl_cache.py`) para esses repositórios, ou usar `INSERT ... ON CONFLICT DO NOTHING RETURNING`. | Baixo. |
| M7 | `database/repositories/base_repository.py:35-42` (`add`/`delete`) | Fazem `session.flush()` incondicional a cada chamada — qualquer loop que chama `repo.add()`/`repo.delete()` por item vira N flushes (achado em `punishment_service.py:182-188`, `vote_weight_service.py:80-81`, `giveaway_service.py:172-200`). | MEDIO (abrangência, não gravidade por caso) | Helper `add_all`/`delete_many` com um único `flush()`. | Baixo. |
| M8 | `core/bot.py:153` (`setup_hook`) | `tree.sync()` global chamado incondicionalmente em todo boot de produção (sem test guild). Redeploys frequentes disparam sync global repetido — rate limit mais restrito que sync por guild. | MEDIO | Sincronizar só quando o command tree realmente mudou (hash/diff). | Baixo-médio — precisa lógica de detecção de mudança confiável. |
| M9 | `main.py:42-56` (`_run_startup_migrations`) | `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` rodado direto no startup, fora do Alembic. Idempotente e seguro, mas é drift de schema fora da ferramenta de migration. | MEDIO | Consolidar em migration Alembic real e remover o hack. | Baixo. |
| M10 | `api/routes/internal_routes.py` (reconcile) | Sem limite de concorrência nas chamadas Discord (`add_roles`/`remove_roles`) durante reconciliação grande — risco de esbarrar em rate limit e atrasar buckets do bot (mesmo HTTP client). | MEDIO | Semáforo (junto com A1). | Baixo. |
| M11 | `cogs/partnership.py:69` (`announcement_tick`, 1 min) | Itera `for guild in bot.guilds` incondicionalmente a cada minuto, mesmo para guilds com parceria desabilitada — ao contrário de `painel.py`/`bot_status.py`/`subscription_renewal.py` que já pré-filtram via query (`list_*_with_*`). | MEDIO | Trocar por query pré-filtrada "guilds com parceria habilitada", mesmo padrão já usado em outros cogs. | Baixo. |
| M12 | `services/plan_service.py`, `services/product_service.py:59` (`soft_delete`) | Achados de código morto que tocam monetização — ver seção Código Morto. | MEDIO (risco de remoção, não de perf) | Investigar antes de remover. | — |
| M13 | `database/repositories/punishment_repository.py:126` (`list_expired_active_temp_bans`) | Zero chamadores encontrados — mas nome sugere lógica crítica (auto-expirar temp ban). Pode ser reimplementado inline em `cogs/moderation.py` `@tasks.loop`, o que explicaria zero-callers sem lacuna real — **precisa verificação, não é achado de perf puro**. | MEDIO-ALTO (risco funcional se for lacuna real) | Confirmar se `review_expiration_task` cobre a expiração de temp ban; se não cobrir, é bug funcional, não código morto. | — |

---

## Baixos

- `utils/appeal_dm.py:24-41` `DMAppealRateLimiter._attempts` — chave nunca removida mesmo com lista vazia; vazamento lento, mesmo formato de outros rate-limiters já corrigidos no projeto. BAIXO.
- `services/config_service.py` — `get_evaluation_settings`/`get_dashboard_settings`/`get_bot_status_settings` não usam o TTLCache que outras settings já usam; consistência, não urgência.
- `providers/storage/s3_compatible.py:53` — `boto3.generate_presigned_url` síncrono, mas é cálculo local (sem I/O de rede); sinalizar só caso um upload real (`put_object`/`upload_file`) seja adicionado sem `to_thread` no futuro.
- `database/repositories/*.py` — vários `select(Model)` completo quando só PK/existência é necessária (ex.: locks). Overhead pequeno.
- `~59 chamadas` de `session.refresh()` após `flush()` quando o valor já é conhecido em memória — round-trip extra evitável em vários pontos (ex.: `booster_service.py:145`).
- `database/repositories/audit_log_repository.py:31,36` — `ILIKE '%...%'` com wildcard à esquerda não usa índice btree; hoje aceitável (filtrado por guild_id antes), mas escala mal.
- Logging: nenhum achado acima de BAIXO — disciplina boa (sem log por mensagem, sem log por query, `echo=False` no SQLAlchemy).

---

## Código morto

Todos os cogs são carregados dinamicamente (`core/bot.py: _load_cogs`, via `pkgutil`), então nenhum arquivo de cog inteiro é "morto" — falsos positivos de linter estático foram descartados. A lista abaixo é grep-verificada (zero chamadores fora da própria definição).

| Arquivo | Função/Classe | Refs | Quem chama | Risco remoção | Recomendação |
|---|---|---|---|---|---|
| `services/plan_service.py:236,256,330` | `add_benefit`, `remove_benefit`, `list_messages` | 0 | ninguém | Baixo | Confirmar se UI de planos não usa dinamicamente; remover. |
| `services/help_service.py:55,103` | `register_command`, `remove_command` | 0 | ninguém | Baixo-médio | Verificar se registro de comandos de ajuda usa lista estática em vez disso. |
| `services/license_service.py:186` | `expire_license` | 0 em produção (testado em `tests/test_license_service.py`) | — | Médio | Tem teste mas sem chamador real — provável gap entre feature planejada e reconciliação atual. Investigar antes de remover. |
| `services/booster_service.py:72` | `list_boosters` | 0 | ninguém | Baixo | Remover ou expor em comando admin. |
| `services/giveaway_service.py:209` | `list_winners` | 0 | ninguém | Baixo | Provável lógica inline em `cogs/giveaways.py`; confirmar e remover. |
| `services/punishment_service.py:522` | `get_appeal` | 0 | ninguém | Baixo-médio | Checar se `views/pending_punishments_view.py` usa o repositório direto. |
| `services/partnership_service.py:46,67` | `PartnershipError`, `member_is_partnership_staff` | 0 em produção | testes usam a exceção | Baixo | Classe/função nunca usada em produção; remover. |
| `services/poll_service.py:44` | `render_poll_placeholders` | 0 | ninguém | Baixo | Possível duplicação com `views/enquete_panel_view.py`; consolidar. |
| `services/product_service.py:59` | `soft_delete` | 0 | ninguém | **Médio** (dados de monetização) | Confirmar se delete de produto usa cascade de license_service antes de remover. |
| `database/repositories/base_repository.py:27` | `list_all` | 0, com aviso próprio no código sobre uso sem filtro de guild_id | ninguém | Baixo | Já desencorajado por comentário existente; remover ou reforçar guard. |
| `database/repositories/giveaway_repository.py:41` | `get_by_giveaway_and_user` | 0 | ninguém | Baixo | Remover. |
| `database/repositories/license_repository.py:15,83` + `subscription_repository.py:14,87` | `get_by_external_reference`, `list_expiring_active` (duplicado nos dois repos) | 0 nos 4 | ninguém | Médio | Verificar se `PaymentService`/`WebhookService` usam lookup alternativo antes de remover os 4. |
| `database/repositories/partnership_repository.py:20` | `get_by_guild_owner_locked` | 0 | ninguém | Baixo | `get_by_channel` (32 refs) parece ser o caminho real. |
| `database/repositories/payment_status_history_repository.py:14` | `list_by_payment` | 0 | ninguém | Baixo | Sem view de timeline de pagamento ainda; remover ou implementar. |
| `database/repositories/plan_repository.py:19` | `get_by_guild_and_name` | 0 | ninguém | Baixo | Remover. |
| `database/repositories/poll_repository.py:41` | `get_by_poll_and_user` | 0 | ninguém | **Médio** | Pode indicar checagem de voto duplicado feita só via constraint do banco, sem guard de aplicação — investigar antes de remover. |
| `database/repositories/punishment_repository.py:61,70,126` | `get_last_by_user`, `count_by_type`, `list_expired_active_temp_bans` | 0 cada | ninguém | **Médio-Alto** | `list_expired_active_temp_bans` parece crítica (auto-expirar temp ban) — ver M13 acima. Investigar antes de tocar. |
| `database/repositories/discount_coupon_repository.py:63,122` | `list_by_coupon` (×2 classes) | 0 cada | ninguém | Baixo | UI de cupom provavelmente usa `totals_for_coupon`/`count_for_coupon`. |
| `database/repositories/game_manifest_repository.py:26`, `launcher_version_repository.py:20` | `set_current` (×2) | 0 cada | ninguém | Baixo | Checar rotas internas do launcher antes de remover. |
| `providers/base.py:69`, `providers/manual.py:76`, `providers/mercadopago.py:157` | `create_subscription` (interface + 2 implementações) | 0 | ninguém | Médio | ~60 linhas de superfície morta — parece stub de cobrança recorrente nunca ligado ao fluxo atual (PIX/manual reconciliado por `ReconciliationService`). Não remover sem confirmar com dono do produto. |
| `config/settings.py:128,144` | `is_production`, `mercadopago_public_key` (properties) | 0 | ninguém | Baixo | Campos-base ainda são lidos; só a property de conveniência está morta. |

**Divergência arquitetural (não é código morto, mas achado da seção 1):**
- `cogs/backup.py` e `cogs/logs.py` acessam repositório/sessão de banco direto, pulando a camada de service.
- `services/audit_log_service.py` e `services/config_reset_service.py` importam de `views/` — dependência invertida (service → view).
- `cogs/audit.py` (comando `/auditoria`) e `cogs/audit_logs.py` (listeners de trilha) são dois sistemas distintos com nomes quase iguais — não é bug, mas confunde manutenção.

---

## Queries problemáticas

Ver tabelas em Altos (A3, A4, A5) e Médios (M4-M7) acima — resumo:
- Falta de índice composto `(guild_id, user_id)` em punishments/subscriptions/payment_history.
- Falta de índice em `status` para as 4 queries de sweep periódico (moderation review, unban, renovação, expiração de pagamento) — hoje table scan.
- `count_open_by_member` (criação de ticket) sem índice em `opened_by_discord_id`.
- Model/schema drift: índices de `user_id` existem no banco via migration raw mas não no `Column(index=True)` do model.
- `ILIKE '%...%'` em audit log search sem índice trigram — baixo risco hoje, cresce mal.
- `get_or_create` (settings) sem upsert atômico nem cache em 3 repositórios (booster/partnership/subscription-renewal), diferente do padrão já usado em `config_service.py`.

---

## N+1

| Local | Padrão | Prioridade (conforme pedido: tickets/subscriptions/payments/punishments/partnerships/boosters/verification/automod/audit logs) |
|---|---|---|
| `services/subscription_reminder_service.py:99-360` | Settings/templates/botões recarregados por assinatura, dentro do loop | **Alta** (subscriptions) |
| `services/booster_service.py:97-199` | Settings recarregadas por membro divergente | **Alta** (boosters) |
| `services/partnership_service.py:120-206` | Settings/role-ids/partnership recarregados por membro divergente | **Alta** (partnerships) |
| `services/punishment_service.py:182-188` | Insert de role por role em loop (1 flush cada, via `base_repository.add`) | Baixa (punishments — volume pequeno por chamada) |
| `services/vote_weight_service.py:80-81` | Delete por item em loop | Baixa |
| `services/giveaway_service.py:172-200` | Insert de vencedor por vencedor em loop | Baixa |
| `api/routes/player_routes.py:26-53` | `product_service.get()` por licença em loop, em vez de lookup em lote | Baixa-média |
| `services/coupon_service.py` (via `discount_coupon_repository.py:75-84`) | Ver Crítico C1 — não é N+1 de leitura, é bug de escrita duplicada | **Crítico** |

Nenhum N+1 encontrado em verification ou automod (fluxos já usam consulta única/cache) nem em audit logs (escrita é por evento, não em loop).

---

## Tasks

Todas as `@tasks.loop` são declaradas por cog, iniciadas 1x em `__init__`, canceladas em `cog_unload`, protegidas por `before_loop -> wait_until_ready()`. Nenhuma duplicação de start encontrada (cog é carregado 1x pelo loader dinâmico).

| Task | Arquivo:linha | Intervalo | Itera guilds/members? | Concorrência própria | Observação |
|---|---|---|---|---|---|
| `check_inactive_tickets` | `cogs/inactivity.py:41` | 5 min | `for guild in bot.guilds`, sequencial | sem lock (não precisa) | Ver M2 (2x history por ticket). |
| `sweep_expired_verifications` | `cogs/verification.py:54` | 1 min | não | — | OK. |
| `review_expiration_task` | `cogs/moderation.py:89` | 1 min | não (query por expiry) | — | Ver M13 — confirmar cobertura de temp ban. |
| `close_expired_polls` | `cogs/polls.py:186` | few min | não | — | OK. |
| `close_expired_giveaways` | `cogs/giveaways.py:216` | few min | não | — | OK. |
| `check_subscription_renewals` | `cogs/subscription_renewal.py:37` | 15 min, throttle por guild | não (settings pré-filtradas) | throttle dict | OK, ver A6 para N+1 dentro do ciclo. |
| `auto_update_dashboards` | `cogs/painel.py:35` | 1 min, throttle | não | throttle dict | Bom padrão (pré-filtro + throttle) — modelo a copiar. |
| `auto_update_status` | `cogs/bot_status.py:34` | 1 min, throttle | não | throttle dict | Idem. |
| `reconcile_licenses` | `cogs/license_reconciliation.py:30` | 60 min | `for guild in bot.guilds` (dentro do service) | **`asyncio.Lock`** já implementado | Bom — mas ver A1 (gather sem semáforo dentro do service). |
| `reconcile_partnerships` | `cogs/partnership.py:55` | 60 min | `for guild in bot.guilds`, sequencial | sem lock | OK, cadência baixa. |
| `announcement_tick` | `cogs/partnership.py:67` | 1 min | `for guild in bot.guilds`, **sem pré-filtro** | — | Ver M11. |
| `reconcile_boosters` | `cogs/boosters.py:39` | 60 min | `for guild in bot.guilds` + `fetch_member` por divergente | sem lock | Ver A7 (N+1). |
| `check_expired_payments` | `cogs/payment_expiration.py:30` | 5 min | não | — | OK. |
| `check_stale_tickets` | `cogs/reminders.py:33` | 5 min | `for guild in bot.guilds`, sequencial | sem lock | Baixo risco, custo pequeno por guild ociosa. |
| `daily_backup` | `cogs/backup.py:87,235` | 24h | `for guild in bot.guilds` (2x, `_run` e `_check_monthly_top1`) | sem lock | Cadência baixa, ver M1 (JSON dump síncrono). |

**Achado isolado fora da tabela:** `utils/ticket_lifecycle.py:31` (`schedule_channel_deletion`) usa `asyncio.create_task(...)` sem guardar referência (sem `set` + `add_done_callback`, ao contrário do padrão já certo em `services/painel_service.py:48-62`). Janela de risco pequena (delay padrão 10s), mas é o mesmo tipo de bug que o projeto já corrigiu em outro lugar. MEDIO.

---

## Event loop

Nenhum bloqueio confirmado do tipo clássico (`requests`, `urllib`, `time.sleep`, `subprocess` síncrono, `os.walk` pesado) — busca no repo inteiro não encontrou nenhum. Já existe teste de regressão dedicado (`tests/test_no_blocking_event_loop_calls.py`) e uso correto de `asyncio.to_thread` para matplotlib/xhtml2pdf/zip.

| Achado | Severidade |
|---|---|
| `cogs/backup.py:149-185` — JSON dump síncrono não movido para `to_thread` (ao lado do zip que já foi) | MEDIO (M1) |
| `providers/storage/s3_compatible.py:53` — boto3 `generate_presigned_url` síncrono, mas é cálculo local sem rede | BAIXO |
| `cogs/inactivity.py:107` — cadeia de awaits HTTP escalando com guilds × tickets abertos | BAIXO/INFO |
| `api/routes/internal_routes.py` reconcile — não bloqueia tecnicamente, mas monopoliza turnos do loop por tempo longo | Ver A1/A2 |

Nenhuma rota FastAPI bloqueia o loop no sentido clássico — resposta direta à pergunta prioritária do pedido: **o bot e a API compartilham processo/loop (confirmado em `main.py`), mas nenhuma rota HTTP encontrada faz chamada síncrona bloqueante.** O risco real é de contenção de turnos (rota reconcile), não de lock do loop.

---

## Discord API

- Padrão geral bom: quase todo `fetch_member`/`fetch_user` é precedido por `get_member`/`get_user` (cache local) e envolto em `try/except HTTPException/NotFound`.
- `cogs/inactivity.py:73,82` — 2 chamadas `channel.history(limit=200)` por ticket aberto a cada 5 min (ver M2).
- `services/painel_service.py refresh_dashboard` — edits concorrentes na mesma mensagem sob rajada (ver M3).
- `services/booster_service.py`, `role_sync_service.py`, `subscription_reminder_service.py` — `fetch_member` sequencial, um por vez, sem concorrência limitada (BAIXO — discord.py já rate-limita internamente).
- Nenhum `fetch_*` sem tratamento de erro encontrado.

---

## Memória

- `utils/appeal_dm.py` `DMAppealRateLimiter._attempts` — chave nunca removida (BAIXO, vazamento lento).
- `cogs/antispam.py`, `core/rate_limiter.py` — sweep periódico correto, sem leak.
- `on_guild_remove`/`on_member_remove`/`on_message`/`on_interaction` — nenhuma estrutura em memória por guild sem limpeza encontrada (settings usam TTLCache, não dict global sem TTL).
- Persistent Views registradas 1x no startup (`core/bot.py:178-230`), não por interação — correto.
- `services/painel_service.py` — `set` de background tasks com `add_done_callback` — correto.
- Único ponto sem esse padrão: `utils/ticket_lifecycle.py:31` (ver seção Tasks).

---

## Cache

| Cache | Chave | Conteúdo | TTL | Invalidação | Isolamento guild | Risco |
|---|---|---|---|---|---|---|
| `services/config_service.py` (`_settings_cache` etc.) | `guild_id` | settings row | 300s (`utils/ttl_cache.py`) | manual, em todo write | Sim | Baixo — bem implementado. Falta invalidar em `on_guild_remove` (menor, não urgente). |
| `services/vote_weight_service.py` | `guild_id` | lista de pesos | 300s | idem | Sim | Baixo. |
| `config/settings.py` `lru_cache(maxsize=1)` | global | config de app (não por tenant) | eterno | N/A | N/A (não é por guild) | Nenhum. |
| `get_evaluation_settings`/`get_dashboard_settings`/`get_bot_status_settings` | — | **sem cache** | — | — | — | Oportunidade perdida (BAIXO), não risco. |

Nenhum cache sem TTL, sem limite, ou com risco de vazamento cross-guild encontrado.

---

## FastAPI

- `api/main.py` — CORS fechado por padrão, rate limiting aplicado nas rotas, webhooks verificam assinatura. Sem achados.
- `api/routes/internal_routes.py` `/internal/reconcile` — ver A1/A2/M10.
- `api/routes/player_routes.py` — N+1 leve (product lookup por licença) e ausência de paginação, mas volume inerentemente pequeno (BAIXO-MEDIO).
- `api/routes/launcher_routes.py` — já tem paginação (`le=100`), sem achado.
- Todas as chamadas HTTP externas usam `aiohttp` (assíncrono) — sem `requests` síncrono em lugar nenhum.

---

## Startup

- `main.py:_run_startup_migrations` — ALTER TABLE fora do Alembic, idempotente mas smell (M9).
- `core/bot.py:setup_hook` — sem preload pesado por guild, carregamento de cogs é O(1) em nº de guilds. Bom.
- `core/bot.py:153` — `tree.sync()` global incondicional em todo boot (M8).
- Branch de test guild faz 2 syncs por boot (BAIXO, esperado em dev).
- Nenhuma chamada HTTP externa bloqueante antes de `bot.start()`.
- Nenhuma task iniciada mais de uma vez.

---

## Recomendações (ordem de prioridade sugerida)

1. **Corrigir C1** (bug de dados em cupom) — é bug funcional, não otimização, prioridade imediata.
2. **Resolver os 3 heads do Alembic** (A9) — bloqueia deploy de migration nova.
3. **Adicionar índices** de A3/A4/A5/M4/M5 — mudança aditiva, baixo risco, alto ganho conforme dados crescem.
4. **Limitar concorrência em `reconcile_all_guilds`** (A1/M10) e **tornar `/internal/reconcile` assíncrono** (A2).
5. **Cache de canais de ticket** para tirar query por mensagem (A8).
6. **Hoisting de settings para fora do loop** em subscription_reminder/booster/partnership services (A6/A7).
7. Resto dos Médios/Baixos — ganho menor, aplicar quando mexer nos arquivos por outro motivo.
8. Código morto: **investigar antes de remover** os itens marcados Médio/Médio-Alto (principalmente `list_expired_active_temp_bans`, `get_by_poll_and_user`, `soft_delete` de produto — podem ser lacuna funcional, não código morto de verdade). Os de risco Baixo podem ser removidos com confirmação simples de grep + teste.

Nenhuma recomendação acima remove lock, validação de guild_id, isolamento multi-guild, ou atomicidade de pagamento/assinatura/cupom.

---

# Implementação

## Fase 0 — Baseline

- **ruff:** 32 erros pré-existentes (11 SIM105, 6 UP037, 4 I001, 3 SIM102, 2 B904, 2 B905, 1 E731, 1 F401, 1 SIM117, 1 UP046). Nenhum tocado nesta etapa — fora do escopo desta implementação.
- **py_compile:** OK, projeto inteiro compila sem erro.
- **pytest (sem JWT_SECRET_KEY/DISCORD_OAUTH_* no .env):** 313 passed, 4 failed, 11 errors. Os 11 errors eram `SettingsError` por falta de env var em `tests/test_audit_fixes_validation.py` (suíte de integração contra Postgres real). Com essas variáveis fornecidas via ambiente (não persistidas em `.env`): **325 passed, 6 failed** — os 6 são pré-existentes e não relacionados a esta etapa (4 já falhavam antes por constantes desatualizadas em `AuditLogCategory`/`HelpMainView`; 2 só ficaram visíveis porque antes erravam mais cedo: bug de mock `_FakeResponse` sem `.defer()`, não relacionado a banco/performance).
- **Alembic:** `alembic heads` mostrou só 1 head (`7d3a9e1c4f68`). A auditoria original relatou 3 heads — checado manualmente e confirmado que era falso positivo do parser do agente de auditoria (não reconheceu `down_revision` em tupla). A migration `c7d4a1e8f2b6` já mescla os dois heads divergentes. Fase 2 não precisou de migration de merge.
- Nenhuma alteração de schema fora de migrations Alembic versionadas; nenhum comando destrutivo executado.

## Fase 1 — Bug do cupom

**Arquivos alterados:** `database/repositories/discount_coupon_repository.py`, `tests/test_audit_fixes_validation.py`

`DiscountCouponPlanRepository.replace_for_coupon` executava o mesmo loop de insert+flush duas vezes seguidas na mesma transação (bug de código, não race condition entre requests) — violava `uq_discount_coupon_plan` sempre que a lista de planos não era vazia. Corrigido removendo a duplicação. Também foi adicionado `SELECT ... FOR UPDATE` na linha do cupom antes do delete/insert, serializando duas chamadas concorrentes para o mesmo `coupon_id` — sem isso, a concorrência real ainda conseguia colidir no unique constraint mesmo após corrigir a duplicação (confirmado por teste antes/depois do lock).

**Testes criados** (Postgres real, `guild_id` sentinela, cleanup em `finally`): criação normal sem duplicata, duas chamadas concorrentes no mesmo cupom sem exceção e com estado consistente, rollback de delete anterior quando o insert falha por FK inválida. 3/3 passed, sem regressão na suíte completa.

## Fase 2 — Alembic

Nenhuma ação necessária — já havia 1 head só (ver Fase 0). Migration de merge não foi criada por não haver divergência real.

## Fase 3 — Índices

### Método

Nenhum índice foi criado só porque uma coluna aparece em WHERE. Cada candidato passou por: leitura do repository real → grep de quem chama o método (services/cogs) → confirmação de que a query roda em produção (não é código morto) → checagem dos índices já existentes via `pg_indexes` no Postgres real → confirmação dos labels reais de enum via `pg_enum` (SQLAlchemy grava o NOME do membro Python — ex. `'PENDING_REVIEW'` — não o `.value`; validado no banco, não assumido).

Isso descartou índices que a auditoria original tinha sugerido:
- `PunishmentRepository.list_expired_active_temp_bans`, `get_last_by_user`, `count_by_type` — zero chamadores confirmados por grep em todo o repo. `list_expired_active_temp_bans` parecia crítica (auto-expirar ban temporário), mas `cogs/moderation.py` não tem nenhuma lógica de expiração de temp ban — é lacuna funcional real (feature nunca ligada), não índice faltando. Fica para a Fase 13; nenhum índice criado para query que não roda.
- `SubscriptionRepository.list_expiring_active` — zero chamadores. O scheduler de renovação usa `list_active_with_period(guild_id)` (por guild), não essa. O índice global `(status, current_period_end)` sugerido originalmente teria sido criado para uma query morta.

### Índices analisados (resumo por tabela)

| Tabela | Índices antes | Unique/PK | Queries reais mapeadas |
|---|---|---|---|
| `punishments` | `ix_punishments_guild_id`, `ix_punishments_user_id` | PK, unique `punishment_code` | `list_by_user`, `has_revoked_punishment`, `has_open_punishment_of_type`, `list_pending_review`, `list_expired_pending_reviews` (viva, cron 1min global); `get_last_by_user`/`count_by_type`/`list_expired_active_temp_bans` mortas |
| `subscriptions` | `ix_subscriptions_guild_id`, `ix_subscriptions_user_id` | PK, unique `(guild_id,user_id,plan_id)`, unique `external_reference` | `list_active_by_user`, `list_active_or_pending_by_user`, `list_active_with_period` (viva, cron 15min/guild); `list_expiring_active` morta |
| `payment_history` | `ix_payment_history_guild_id`, `ix_payment_history_user_id` | PK, unique `(provider,external_id)` | `list_pending_expired` (viva, cron 5min global), `list_by_user` |
| `tickets` | `ix_tickets_guild_id` | PK, unique `channel_id` | `count_open_by_member` (hot path), `list_open_by_guild`/`list_awaiting_first_response` (crons 1-5min), `list_by_staff`/`most_common_category_for_staff` |
| `verification_sessions` | `ix_verification_sessions_guild_id`, `ix_verification_sessions_guild_user` | PK | `get_pending_by_guild_user(_locked)` já coberta; `list_expired_pending` (viva, cron 1min global) |
| `boosters` | `ix_boosters_guild_id` | PK, unique `(guild_id,user_id)` | `get_by_guild_user(_locked)` já coberta; `list_active_by_guild` (cron 60min, baixa prioridade) |
| `partnerships` | `ix_partnerships_guild_id` | PK, unique `(guild_id,owner_id)` | `get_by_guild_owner(_locked)` já coberta; `get_next_to_announce` (viva, cron 1min global) |
| `audit_log_entries` | `ix_audit_log_entries_guild_id`, `ix_audit_log_entries_config_name` | PK | `ILIKE` sob demanda (comando `/auditoria`), não periódico |

### Índices criados

| # | Tabela | Índice | Colunas | Query beneficiada | Ordem das colunas | Ganho esperado |
|---|---|---|---|---|---|---|
| 1 | punishments | `ix_punishments_guild_user_created` | `(guild_id, user_id, created_at DESC)` | `list_by_user`, `has_revoked_punishment`, `has_open_punishment_of_type` | guild_id (tenant) → user_id (igualdade) → created_at DESC (casa com ORDER BY, evita Sort) | Cresce com volume por guild |
| 2 | punishments | `ix_punishments_pending_review_deadline` | `(review_deadline_at)` parcial `WHERE status='PENDING_REVIEW'` | `list_expired_pending_reviews` — cron 1min, sem filtro de guild | parcial: fatia pequena/transitória, sem guild_id porque a query não filtra por guild | Sweep global a cada 1 min |
| 3 | subscriptions | `ix_subscriptions_guild_status` | `(guild_id, status)` | `list_active_by_user`, `list_active_or_pending_by_user`, `list_active_with_period` (cron 15min/guild) | guild_id → status (eixo que o unique guild+user+plan não cobre) | Médio, cresce com assinaturas/guild |
| 4 | payment_history | `ix_payment_history_guild_user_created` | `(guild_id, user_id, created_at DESC)` | `list_by_user` | mesmo raciocínio do #1 | Médio |
| 5 | payment_history | `ix_payment_history_pending_expires` | `(expires_at)` parcial `WHERE status='PENDING'` | `list_pending_expired` — cron 5min, sem filtro de guild | mesmo raciocínio do #2 | Sweep global a cada 5 min |
| 6 | tickets | `ix_tickets_open_by_guild_member` | `(guild_id, opened_by_discord_id)` parcial `WHERE status IN ('OPEN','CLAIMED')` | `count_open_by_member` (hot path de abrir ticket), `list_open_by_guild`, `list_awaiting_first_response` | parcial: tickets fechados/cancelados (maioria) nunca entram | Alto conforme base de tickets cresce |
| 7 | tickets | `ix_tickets_staff_created` | `(claimed_by_staff_id, created_at DESC)` | `list_by_staff`, `most_common_category_for_staff` | claimed_by_staff_id (igualdade) → created_at DESC (ORDER BY) | Pequeno, consistente |
| 8 | verification_sessions | `ix_verification_sessions_pending_expires` | `(expires_at)` parcial `WHERE status='PENDING'` | `list_expired_pending` — cron 1min, sem filtro de guild | mesmo raciocínio do #2/#5 | Sweep global a cada 1 min (tabela com mais linhas hoje) |
| 9 | partnerships | `ix_partnerships_guild_announce` | `(guild_id, last_announced_at)` parcial `WHERE archived_at IS NULL` | `get_next_to_announce` (rodízio de divulgação, cron 1min todas as guilds), `list_active_by_guild` | guild_id → last_announced_at (casa com ORDER BY...NULLS FIRST + LIMIT 1); parcial exclui arquivados | Elimina o Sort visto no EXPLAIN (ver Performance) |

Os 9 índices foram replicados no `__table_args__` dos models SQLAlchemy correspondentes (`punishment.py`, `subscription.py`, `payment.py`, `ticket.py`, `verification_session.py`, `partnership.py`) para não repetir o mesmo drift model↔schema já encontrado na auditoria (M4).

### Índices considerados e rejeitados

- `(status, current_period_end)` global em subscriptions: query que justificava (`list_expiring_active`) é código morto (zero chamadores) — substituído pelo #3, que cobre a query realmente usada.
- Índice para `list_expired_active_temp_bans`/`get_last_by_user`/`count_by_type` (punishments): zero chamadores; `list_expired_active_temp_bans` revela lacuna funcional (temp ban não é auto-expirado em lugar nenhum), questão para a Fase 13.
- `boosters(guild_id, currently_boosting)`: cron de 60min + `ix_boosters_guild_id` existente já estreita bem o escopo; frequência baixa não justifica.
- Índice trigram (`pg_trgm`) em `audit_log_entries`: busca `ILIKE` é sob demanda, não periódica; extensão nova desproporcional ao volume atual.
- `subscriptions`/`payment_history` `(guild_id,user_id)` simples: já cobertos por índice único existente (subscriptions) ou pelos índices #1/#4 (com created_at).
- `punishments.list_pending_review` (painel `/analises`): acionado por staff, não periódico; índice guild_id existente já reduz bem o escopo.
- `partnerships.get_by_channel`: acionado por evento, não periódico; volume pequeno por guild.
- `CREATE INDEX CONCURRENTLY`: `alembic/env.py` roda cada migration dentro de uma transação (`context.begin_transaction()`), e Postgres não permite `CONCURRENTLY` em bloco transacional. Tabelas hoje têm poucas dezenas de linhas — lock breve de `CREATE INDEX` normal é desprezível. Documentado no cabeçalho da migration para revisitar com `autocommit_block()` se as tabelas crescerem muito.

### Índices redundantes encontrados (não removidos nesta fase)

`ix_punishments_user_id`, `ix_subscriptions_user_id`, `ix_payment_history_user_id` (single-column) ficam parcialmente redundantes para consultas `guild_id+user_id` depois dos índices #1/#3/#4. Não removidos porque: (a) podem servir queries hipotéticas que filtram só por `user_id`, nenhuma encontrada mas não foi objetivo desta fase provar ausência total; (b) remoção de índice é uma mudança de risco diferente de criação — fica para uma fase de limpeza dedicada, com o mesmo cuidado de "não remover sem confirmar zero uso" já aplicado ao código morto.

### Migration

`alembic/versions/15cdb4300d1a_indices_compostos_hot_paths.py` — down_revision `7d3a9e1c4f68`. Cria os 9 índices; downgrade remove todos na ordem inversa. Nenhuma migration histórica foi modificada.

### Testes (Fase 3)

- `alembic upgrade head`: aplicado com sucesso no banco real (Supabase, `ENVIRONMENT=development` no `.env`; único banco disponível, mesmo usado pela suíte de integração já existente).
- Verificação direta via `pg_indexes`: 9/9 índices presentes com a definição exata esperada (DESC e predicados parciais corretos, labels de enum em maiúsculas confirmados).
- `alembic downgrade -1`: removeu os 9 índices sem erro.
- `alembic upgrade head` novamente: recriou os 9 sem erro. `alembic heads` confirma 1 head só (`15cdb4300d1a`) ao final.
- `ruff check .`: 32 erros, igual ao baseline — nenhum novo.
- `py_compile`: OK.
- `pytest`: 325 passed, 6 failed (os mesmos 6 pré-existentes do baseline) — sem regressão.

### Performance (antes/depois)

`EXPLAIN` rodado nas 6 queries mais representativas contra o banco real, antes e depois da migration. Tabelas hoje têm 1-74 linhas (punishments=12, subscriptions=7, payment_history=16, tickets=21, verification_sessions=74, partnerships=4) — nesse volume o planner do Postgres corretamente prefere Seq Scan pra maioria (custo estimado ~1.0-2.3 em ambos os planos, diferença na casa do ruído). Único ganho estrutural já visível: `get_next_to_announce` (partnerships) deixa de precisar de um nó `Sort` explícito. Fora esse caso: **ganho não mensurado neste ambiente** — os índices foram desenhados a partir do padrão de consulta e da natureza cross-guild de crons que rodam a cada 1-5 min sobre a tabela inteira sem filtro de guild, não de um benchmark que tabelas desse tamanho não conseguem demonstrar. Ganho real esperado conforme o volume de produção cresce ao longo de semanas/meses.

### Critério de conclusão da Fase 3

Atendido: queries críticas analisadas com base em chamadores reais (não suposição) → índices existentes verificados via `pg_indexes` → nenhum índice novo redundante com o que já existia → todo índice composto justificado por query e ordem de coluna → migration com upgrade/downgrade testados → Alembic com 1 head só → sem regressão em testes/ruff/py_compile.

---

## Fase 4 — Reconciliação

### Investigação (mapa real, confirmado no código)

```
tasks.loop(minutes=60) LicenseReconciliationCog.reconcile_licenses
POST /internal/reconcile (api/routes/internal_routes.py) — sob demanda, staff/backend
        │
        ▼
ReconciliationService.reconcile_all_guilds()   [services/reconciliation_service.py]
        │  asyncio.Lock() serializa disparo periódico vs disparo sob demanda
        ▼
asyncio.gather(*(reconcile_guild(g) for g in self._bot.guilds))   ← SEM LIMITE
        │
        ▼  (por guild)
PlanRepository.list_by_guild(guild.id)         — 1 query
        │
        ▼  (por plano com product_id + role_id)
_reconcile_plan: PlayerRepository.list_by_discord_ids + LicenseRepository.list_active_by_players_and_product
                 + LicenseRepository.list_active_by_product + PlayerRepository.list_by_ids   — 4 queries batched (sem N+1, já corrigido antes desta fase)
        │
        ▼  (por divergência encontrada)
_fix_divergence: member.add_roles / member.remove_roles (Discord HTTP) → audit_log_service.record (1 INSERT)
```

Não é feature nova nem código morto: único caminho de reconciliação existente no bot, chamado pelos dois gatilhos confirmados acima.

### Problema encontrado

`reconcile_all_guilds` (services/reconciliation_service.py:64, antes da mudança) despachava `asyncio.gather` sobre **todas** as guilds do bot sem `Semaphore` nem limite algum — confirmado no código, não presumido pelo relatório original. Com N guilds, isso dispara N sessões de DB (`self._database.session()`, um pool compartilhado de 10+20 com a API FastAPI — ver `config/settings.py: db_pool_size`) e N rajadas de chamadas Discord (`add_roles`/`remove_roles`) simultâneas, competindo pelo mesmo event loop que também serve comandos e eventos do bot.

Sem timeout por guild: uma guild lenta (Discord devagar, DB devagar) ficava presa dentro do `gather` até `HTTPException`/erro de fato — sem teto de tempo.

Isolamento por guild já existia (`return_exceptions=True` + captura por `zip`), então uma falha já não derrubava o processo inteiro — mantido, não reescrito.

### Alterações realizadas

`services/reconciliation_service.py`:
- `ReconciliationService.__init__` ganhou `max_concurrency` e `guild_timeout_seconds` (parâmetros nomeados, com default 5 e 30s pra não quebrar quem instancia sem passar nada).
- Novo método `_reconcile_guild_limited(guild, semaphore)`: adquire o `asyncio.Semaphore(max_concurrency)`, roda `reconcile_guild` dentro de `asyncio.wait_for(..., timeout=guild_timeout_seconds)`, captura `TimeoutError` isoladamente (não deixa a exceção subir pro `gather`) e devolve um `GuildReconciliationResult(errors=1, timed_out=True)`.
- `reconcile_all_guilds` agora despacha `_reconcile_guild_limited` (não `reconcile_guild` direto) no `gather`, mede duração total (`time.monotonic()`) e loga o resumo agregado.
- `GuildReconciliationResult` ganhou `timed_out: bool`; `ReconciliationReport` ganhou `timeouts`, `duration_seconds`, `max_concurrency` (campos internos — `ReconciliationReportResponse` da API não mudou, ver seção 8 abaixo).
- `_fix_divergence`: retry limitado (2 tentativas, backoff `1s * tentativa`) só pra `discord.HTTPException` genérico (erro transiente de rede/5xx). `discord.Forbidden`/`discord.NotFound` continuam sem retry (permanentes — retry não resolve).

`config/settings.py`: `reconcile_max_concurrency` (default 5, env `RECONCILE_MAX_CONCURRENCY`) e `reconcile_guild_timeout_seconds` (default 30, env `RECONCILE_GUILD_TIMEOUT_SECONDS`).

`core/bot.py`: `ReconciliationService` agora recebe os dois valores de `settings` na construção.

### Estratégia de concorrência

`asyncio.Semaphore(max_concurrency)` — default 5, configurável por env. Número escolhido pelo comportamento real observado, não arbitrário: o bot roda hoje com poucas guilds (tabelas da Fase 3 mostram volumes de dezenas de linhas), e o pool de DB compartilhado com a API FastAPI tem 10 conexões base (`db_pool_size`); 5 reconciliações simultâneas deixa margem de sobra no pool pro tráfego normal de comandos/API enquanto o ciclo roda. Ajustável via `RECONCILE_MAX_CONCURRENCY` se o número de guilds crescer.

Teste dedicado (`test_reconcile_all_guilds_does_not_allow_six_with_limit_five`) prova que com limite 5 e 6 guilds, o 6º não começa até um dos 5 primeiros liberar o semáforo.

### Timeout

`asyncio.wait_for(reconcile_guild(guild), timeout=guild_timeout_seconds)` por guild — default 30s, configurável via `RECONCILE_GUILD_TIMEOUT_SECONDS`. Guild que estoura o timeout: conta como erro (`errors=1`, `timed_out=True`) no resultado dela, logada como `WARNING`, e **não** afeta as demais guildas em andamento (`return_exceptions=True` no `gather` continua garantindo isso, testado em `test_guild_timeout_does_not_cancel_others`).

### Retry

Só pra `discord.HTTPException` genérico na escrita do cargo (`add_roles`/`remove_roles`) — 2 tentativas no total, backoff de 1s antes da segunda. `discord.Forbidden` (sem permissão) e `discord.NotFound` (cargo/membro sumiu) são tratados como permanentes: 1 tentativa só, sem retry, log de `WARNING` e segue pro próximo membro/plano — retry nesses casos não resolveria e só adicionaria latência. Rate limit (429) já é absorvido internamente pelo HTTP client do discord.py antes de chegar como exceção; este retry não duplica esse mecanismo, cobre só falha transiente pontual (timeout de rede, 5xx).

Não foi implementado retry para timeout de guild (`TimeoutError` do `wait_for`) nem para exceções que escapam de `reconcile_guild` no nível do `gather` — retry automático de uma guild inteira que já estourou 30s round-trip round-trip poderia empilhar atraso sem necessidade real; ela é corrigida no próximo ciclo (60min) ou no próximo disparo manual de `/internal/reconcile`.

### Impacto no event loop

Nenhuma operação síncrona/bloqueante foi encontrada em `reconciliation_service.py` (confirmado por grep: sem `time.sleep`, `requests.*`, leitura de arquivo, `json.load` síncrono) — não havia necessidade de `asyncio.to_thread` nesta fase. O ganho pro event loop vem só da concorrência controlada: em vez de N guilds competindo por fatias de CPU/IO ao mesmo tempo, no máximo `max_concurrency` competem, deixando mais espaço pro loop atender comandos/heartbeat entre as fatias.

### Chamadas Discord reduzidas

Revisado: `_reconcile_plan` já usa `guild.get_role`/`guild.get_member` (cache local, sem fetch remoto) e só chama `add_roles`/`remove_roles` quando já confirmou divergência real via DB — nenhuma chamada Discord redundante ou "sem necessidade" foi encontrada nesta fase (o batching que evita N+1 de banco já tinha sido feito antes da Fase 4, ver código de `_reconcile_plan`). Nenhuma mudança nesta frente além do retry limitado descrito acima.

### `POST /internal/reconcile`

Mantido síncrono (executa a reconciliação dentro da própria request e retorna o relatório completo) — decisão explícita, não omissão:
- O endpoint já é protegido por HMAC + rate limiter (120 req/60s, `api/routes/internal_routes.py`), não é um caminho de tráfego alto.
- Com concorrência limitada + timeout por guild, o tempo de resposta agora tem teto previsível: no pior caso, `ceil(guilds / max_concurrency) * guild_timeout_seconds`.
- A resposta (`ReconciliationReportResponse`) é o relatório real da execução — trocar para fire-and-forget quebraria esse contrato (a suíte de testes existente, `tests/test_internal_routes.py`, já espera o relatório populado na resposta) e exigiria rastreamento de job/status, arquitetura que a Fase 4 explicitamente pede pra não introduzir.
- Nenhuma alteração de API pública foi feita.

### Métricas

`reconcile_all_guilds` agora loga uma linha agregada por execução:

```
Reconciliation completed: guilds=120 success=118 failed=1 timeout=1 duration=18.4s max_concurrency=5
```

Sem log por membro (evitado propositalmente — volume alto e sem valor de debug no dia a dia). Log de `WARNING` só por guild com timeout; `DEBUG` por guild concluída (duração individual, não polui log em `INFO`). Nenhum token/secret exposto (payload já não incluía nada sensível antes desta fase).

### Testes

Adicionados em `tests/test_reconciliation_service.py` (17 testes no arquivo agora, todos passando):
- `test_reconcile_all_guilds_processes_multiple_guilds` — múltiplas guilds processadas.
- `test_reconcile_all_guilds_respects_max_concurrency` — pico de concorrência nunca excede `max_concurrency` (20 guilds, limite 5).
- `test_reconcile_all_guilds_does_not_allow_six_with_limit_five` — prova direta do limite: com 5 guilds presas num `asyncio.Event`, o 6º guild não inicia.
- `test_one_guild_failure_does_not_cancel_others` — uma guild lançando exceção não impede as outras duas.
- `test_guild_timeout_does_not_cancel_others` — guild com `reconcile_guild` travado estoura timeout (`errors=1`, `timed_out=True`), a outra guild completa normalmente.
- `test_reconcile_all_guilds_empty_list` — lista vazia não quebra.
- `test_reconcile_all_guilds_large_quantity` — 100 guilds processadas corretamente.
- `test_fix_divergence_retries_transient_http_error_then_succeeds` — `HTTPException` na 1ª tentativa, sucesso na 2ª → audita normalmente.
- `test_fix_divergence_gives_up_after_max_attempts` — `HTTPException` persistente → desiste após 2 tentativas, sem auditoria (correção não aconteceu).
- `test_fix_divergence_does_not_retry_forbidden` — `discord.Forbidden` não tenta 2ª vez.
- Testes pré-existentes da Fase 5 (isolamento de erro por plano, agregação por guild etc.) mantidos sem alteração.

### Benchmark

Não executado neste ambiente — o bot local não tem volume real de guilds pra medir contenção de event loop sob carga (mesma limitação já documentada na Fase 3 pra `EXPLAIN`: poucas guilds/linhas disponíveis). Documentando em vez de inventar números: o ganho esperado é estrutural (teto de concorrência simultânea e teto de tempo por guild, ambos ausentes antes), mensurável de verdade só em produção com dezenas+ de guilds reais.

### Riscos

- `max_concurrency=5` e `guild_timeout_seconds=30` são defaults, não medidos sob carga real — ajustáveis por env se produção mostrar necessidade (guild grande demorando mais de 30s legitimamente, por exemplo).
- Retry de 2 tentativas com backoff de 1s adiciona até ~1s de latência extra por divergência com erro transiente — aceitável dado que reconciliação já não é caminho de latência crítica (não é o `/comando` do usuário).

### Pendências

- Nenhuma migration de banco foi necessária nesta fase (sem alteração de schema) — `alembic heads` confirma 1 head só, inalterado (`15cdb4300d1a`).
- `list_expired_active_temp_bans` (lacuna funcional de auto-expiração de temp ban, identificada na Fase 3) segue pendente pra Fase 13, fora do escopo desta fase.
- `tests/test_audit_fixes_validation.py` (14 testes) e 4 testes pré-existentes (`test_help_views`, `test_punishment_review_constants` ×3) já falhavam/erravam **antes** desta fase — confirmado revertendo as mudanças da Fase 4 (`git stash`) e rodando a mesma suíte: mesmo resultado. Causas não relacionadas à reconciliação: `JWT_SECRET_KEY` ausente no `.env` atual (os testes de `test_audit_fixes_validation.py` dependem de banco real via `get_settings()`) e categoria `AuditLogCategory.GIVEAWAY` sem entrada nos mapas de label/cor/target_kind. Fora do escopo da Fase 4, não corrigido aqui.

### Validação

- `ruff check .`: 31 erros — 1 a menos que o baseline da Fase 3 (32); corrigido um `B905` (`zip` sem `strict=`) no próprio arquivo tocado, nenhum erro novo introduzido.
- `py_compile`: OK nos arquivos alterados.
- `pytest` (excluindo `tests/test_audit_fixes_validation.py`, que depende de banco real indisponível neste ambiente — ver Pendências): 323 passed, 4 failed — os mesmos 4 pré-existentes, confirmados via `git stash`. 17/17 testes novos/existentes de `test_reconciliation_service.py` passando.
- `alembic heads`: 1 head só (`15cdb4300d1a`), sem migration nova — Fase 4 não alterou schema.

### Critério de conclusão da Fase 4

Atendido: concorrência ilimitada eliminada (confirmada no código antes da mudança, não presumida) → `Semaphore(max_concurrency)` limita e testado (`test_reconcile_all_guilds_does_not_allow_six_with_limit_five`) → falha de uma guild não derruba as outras (mantido + testado) → timeout por guild funciona e isolado (testado) → sem retry infinito (2 tentativas, erros permanentes sem retry) → nenhum bloqueio síncrono encontrado no event loop (nada pra mover pra thread) → testes passam sem regressão nova → `ruff` sem erro novo (1 a menos) → comportamento funcional (o que a reconciliação corrige) inalterado.

**Aguardando confirmação antes de avançar para a Fase 5.**

**Aguardando confirmação antes de avançar para a Fase 4.**
