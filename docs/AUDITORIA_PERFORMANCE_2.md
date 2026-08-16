# Auditoria de Performance — Fase 2 (BOT LIMERENCE)

Data: 2026-08-16
Escopo: incremental, não-destrutivo. Nenhuma funcionalidade removida ou
reescrita — só redução de round-trips seriais ao Postgres e de trabalho
síncrono no caminho de resposta ao usuário.

Pré-condição respeitada: os arquivos listados como proibidos (`views/ticket_actions_view.py`,
`views/ticket_panel_open_view.py`, `views/ticket_panels_view.py`,
`views/ticket_closed_view.py`, `views/embeds.py`, `services/ticket_panel_service.py`,
`services/config_transfer_service.py`, `views/master_config_view.py`,
`database/models/ticket_settings.py`, `alembic/versions/*`) **não foram editados** —
só lidos para entender o caminho crítico. Durante esta sessão eles continuaram
sendo modificados por outro trabalho em paralelo (confirmado via `git diff --stat`);
as recomendações da seção 7 foram escritas contra o conteúdo observado no
momento da leitura e podem precisar de ajuste fino se a reescrita paralela já
tiver mudado a estrutura ao redor.

Este documento não repete `docs/AUDITORIA_PERFORMANCE.md` nem `RELATORIO_DEFER_3S.md`
— parte do que eles descreveram (defer-first, índices compostos, cache de
settings, reconciliação com semáforo) já está aplicado. Aqui só o que ainda
estava lento.

---

## 1. Gargalos encontrados

### G1 — `cogs/tickets.py:14-21` `on_message`: 1 query por mensagem, em TODO canal do servidor (A8 da auditoria anterior, ainda não corrigido)

```python
@commands.Cog.listener()
async def on_message(self, message: discord.Message) -> None:
    if message.author.bot or message.guild is None:
        return
    ticket = await self.bot.ticket_service.get_by_channel_id(message.channel.id)  # SELECT
    if ticket is None:
        return
    is_staff = message.author.id != ticket.opened_by_discord_id
    await self.bot.ticket_service.record_first_message(message, is_staff)  # abre OUTRA sessão e refaz o MESMO SELECT
```

Evidência: `get_by_channel_id` (linha 273 de `services/ticket_service.py`, antes da mudança) sempre abria uma sessão e rodava `SELECT` — chamado incondicionalmente em `on_message`, que dispara em toda mensagem não-bot de qualquer canal do servidor (não só canais de ticket). Além disso, quando o canal é ticket, `record_first_message` reabre uma segunda sessão para buscar o mesmo `Ticket` de novo.

Impacto: em um servidor com chat ativo fora dos tickets, isso é uma query de banco por mensagem, na esmagadora maioria das vezes para descobrir que "não é ticket" — o resultado mais repetido e mais barato de cachear que existe no sistema.

### G2 — `views/ticket_actions_view.py` `claim()`/`unclaim()`: round-trips serializados que dá pra reduzir sem mexer no arquivo

Cadeia observada (arquivo lido, não editado — está na lista proibida):

```
member_can(...)                              -> cacheado via ConfigService (permission_settings), OK
interaction.response.defer()                 -> Discord API
bot.ticket_service.get_by_channel_id(...)     -> SELECT #1
bot.ticket_panel_service.get_panel_for_ticket -> SELECT #2 (get_panel, SEM cache)
bot.staff_service.ensure_staff(...)           -> SELECT + COMMIT #3  (antes desta fase: sempre)
bot.claim_service.claim_ticket(...)           -> 1 sessão com ~5 statements (locked read, has_prior_claim,
                                                  insert claim+flush, get_or_create stats, log_event) + commit
bot.ticket_service.get_by_channel_id(...)     -> SELECT #4  (busca de NOVO o ticket que claim_ticket já leu,
                                                  só pra pegar category_snapshot pro log)
bot.log_service.record(...)                   -> sessão própria (insert+flush + select settings + commit)
                                                  + possível audit_log_service.record (outra sessão inteira)
                                                  — tudo isso ANTES do followup.send final
bot.painel_service.refresh_dashboard(...)     -> já é fire-and-forget (background), não bloqueia
interaction.followup.send(...)
```

Evidência de que `staff_service.ensure_staff` pagava SELECT+COMMIT em praticamente todo clique mesmo quando nada mudava: `services/staff_service.py:30-42` (antes desta fase) sempre abria sessão, mesmo quando `staff.display_name == display_name`.

Evidência de duplicação: `ticket_service.get_by_channel_id` é chamado 2x na função `claim()` (linhas 69 e 85 do arquivo lido) e `claim_ticket` internamente já carrega o `Ticket` (com `category`) na mesma transação — o segundo fetch é evitável se o serviço devolvesse o dado já carregado, mas mudar a assinatura de `claim_ticket` quebraria o contrato que a view (proibida) espera, então isso vira recomendação (seção 7), não mudança aplicada.

Evidência de que `log_service.record`/`audit_log_service.record` competem pelo orçamento de resposta ao usuário: ambos abrem sessão própria, fazem `INSERT+flush`, um `SELECT` de settings, `COMMIT`, e opcionalmente um `channel.send` (chamada de rede ao Discord) — tudo síncrono, `await`ado, antes de `interaction.followup.send` no fluxo de claim/unclaim/fechar (`services/log_service.py:32-78`, `services/audit_log_service.py:152-215`, ambos lidos antes desta fase).

### G3 — `services/config_service.py`: 4 métodos de settings sem cache (achado M da auditoria anterior, "oportunidade perdida")

`get_evaluation_settings` (lido no fechamento de ticket, `views/ticket_actions_view.py`), `get_dashboard_settings`, `get_bot_status_settings`, `get_ranking_settings` batiam no banco toda vez, ao contrário de `get_settings`/`get_ticket_settings`/`get_permission_settings`/`get_anti_spam_settings`, que já usam `TTLCache`.

### G4 — `services/staff_service.py:30-42`: `ensure_staff` sem cache, chamado em todo clique de Assumir/Liberar

Já descrito em G2 — repetido aqui porque é uma alteração feita em arquivo próprio (não é só recomendação).

---

## 2. Alterações realizadas, arquivo por arquivo

Todas aditivas ou estritamente redutoras de round-trip — nenhum comportamento funcional observável mudou (mesmas mensagens, mesmas condições de erro, mesma consistência de dados).

### `utils/timing.py` (novo)
Helper `timed_step(operation, step)` — context manager assíncrono que loga em `DEBUG` a duração de uma etapa (`db`, etc.) de um fluxo crítico. `logger.isEnabledFor(logging.DEBUG)` evita até formatar a string quando o log está em `INFO`/`WARNING` (produção) — custo ~zero fora de depuração. Não substitui profiling real; é telemetria permanente e barata para responder "que etapa comeu o orçamento de 3s" quando precisar.

### `services/ticket_service.py`
- **Cache negativo de canal** (`_confirmed_non_ticket_channels: set[int]`): `get_by_channel_id` só cacheia o resultado quando é `None`. Isso é seguro porque um `channel_id` só vira ticket na criação, sempre com um canal **recém-criado** pelo Discord (`create_ticket` chama `guild.create_text_channel`) — snowflakes nunca se repetem, então um canal confirmado "não é ticket" nunca vai virar um depois. Quando o ticket **existe**, a busca continua sempre fresca no banco (status/claim mudam o tempo todo — não cacheado, conforme pedido).
- **`forget_channel(channel_id)`** (novo método): remove a entrada do cache negativo. Chamado em `on_guild_channel_delete` para **qualquer** canal deletado, não só tickets — mantém o cache do tamanho dos canais vivos na guild em vez de crescer sem limite pra sempre (item de memória do pedido).
- **`record_first_message_for_channel(message)`** (novo método): combina a checagem "é ticket?" + a gravação da primeira mensagem em **uma única sessão/transação**, usando o cache negativo para sair sem sessão nenhuma quando o canal já foi confirmado como não-ticket. Substitui, no listener, o par `get_by_channel_id` + `record_first_message` (que reabria uma segunda sessão para o mesmo ticket). O método antigo `record_first_message` foi mantido (não tinha outro chamador, mas remover método público sem necessidade não é o objetivo aqui).
- `close_ticket` agora é um wrapper fino (`timed_step("close_ticket", "db")`) em volta do corpo original, renomeado para `_close_ticket_impl` — zero mudança de lógica, só instrumentação sem precisar reindentar ~90 linhas.

### `cogs/tickets.py`
- `on_message` agora chama `record_first_message_for_channel` (1 chamada, 1 sessão no pior caso) em vez do par antigo.
- `on_guild_channel_delete` agora também chama `ticket_service.forget_channel(channel.id)`, além do já existente `mark_deleted_before_service`.

### `services/staff_service.py`
- `TTLCache[(guild_id, discord_user_id), Staff]` com TTL de 120s. `ensure_staff` só bate no banco se não há entrada em cache **ou** se o `display_name` mudou desde o cache (o nick pode mudar a qualquer momento; sem TTL longo, e sem arriscar dado desatualizado por muito tempo — mesmo padrão de risco/trade-off já usado em `ConfigService`). Todos os 5 chamadores (`cogs/claim.py` x2, `views/ticket_actions_view.py` x2) só usam `staff.id`, então cachear o objeto ORM inteiro (detached, `expire_on_commit=False`) é seguro — nenhuma relação lazy é acessada depois.
- Instrumentado com `timed_step("ensure_staff", "db")`.

### `services/claim_service.py`
- `claim_ticket`/`unclaim_ticket` instrumentados com `timed_step(..., "db")` em volta da sessão inteira. Nenhuma mudança de lógica.

### `services/log_service.py`
- Novo método **opt-in** `record_background(**kwargs)`: dispara `record(...)` como `asyncio.Task` rastreada num `set` (mesmo padrão anti-GC de `services/painel_service.py`), retorna na hora. Exceções são capturadas e logadas (`logger.exception`), nunca propagadas. **`record()` em si não mudou** — os ~30 chamadores existentes continuam síncronos, sem risco de regressão nos fluxos que dependem do retorno ou da gravação estar concluída (ex.: punições, pagamentos, cupons).

### `services/audit_log_service.py`
- Mesmo padrão: `record_background(**kwargs)` opt-in, aditivo, `record()` inalterado.

### `services/config_service.py`
- Adicionado `TTLCache` (mesmos 300s dos 4 já existentes) para `get_evaluation_settings`, `get_dashboard_settings`, `get_bot_status_settings`, `get_ranking_settings`, com invalidação em `update_*`/`reset_*` correspondentes — mesmo padrão exato já usado para `get_settings`/`get_ticket_settings`/`get_permission_settings`/`get_anti_spam_settings`.
- Verificado que nenhum desses 4 tem escrita "por fora" do `ConfigService` que ficaria invisível ao cache: `EvaluationSettingsRepository` só é usada em `config_service.py`; `DashboardSettingsRepository`/`RankingSettingsRepository` são lidas (não escritas) diretamente em `services/painel_service.py._refresh_dashboard_impl` (leitura direta, sem cache, continua sempre fresca — não afetado); `BotStatusSettingsRepository` tem uma escrita direta em `services/bot_status_service.py._save_message_id` (salva `message_id`/`channel_id`), mas o único lugar que lê via `config_service.get_bot_status_settings` é o painel de configuração (`views/master_config_view.py`, exibição) — mesma classe de staleness cosmética (até 300s) que os 4 caches já existentes, sem risco de duplicar mensagem de painel (esse fluxo usa a leitura direta, não o cache).

### `tests/test_perf_audit_2.py` (novo)
11 testes de regressão cobrindo tudo isso — ver seção 5.

---

## 3. Melhorias (round-trips seriais ao banco / chamadas Discord por operação)

Convenção: 1 "round-trip" = 1 ida-e-volta de rede ao Postgres (1 `SELECT`/`INSERT`/`UPDATE`/`COMMIT` isolado). Os ms são **estimativa**, não medição real (sem Discord/Postgres real disponível neste ambiente) — fórmula: `ms_estimado = round_trips × RTT_assumido`, com `RTT_assumido` de 30–150ms (faixa plausível para Supabase via pooler a partir de uma VPS/host externo; **não medido aqui**, só citado como referência de ordem de grandeza pela própria tarefa).

| Operação | Round-trips DB (antes) | Round-trips DB (depois) | Chamadas Discord API | Observação |
|---|---|---|---|---|
| Mensagem em canal comum (não-ticket), depois da 1ª vez que o canal é visto | 1 (`get_by_channel_id`) | **0** | 0 | G1 — cache negativo elimina a query pra 100% das mensagens fora de tickets, a partir da 2ª mensagem daquele canal desde o boot |
| Mensagem em canal de ticket ainda sem 1ª resposta registrada | 2 (`get_by_channel_id` + `record_first_message`, 2 sessões) | **1** (sessão única) | 0 | G1 |
| `ensure_staff` (chamado em claim/unclaim) com nick inalterado, staff em cache | 1 SELECT + 1 COMMIT (~2) | **0** | 0 | G4 — só paga o round-trip quando o cache expira (120s) ou o nick mudou |
| `get_evaluation_settings`/`get_dashboard_settings`/`get_bot_status_settings`/`get_ranking_settings`, hit de cache | 1 | **0** | 0 | G3 |
| `claim()` completo (visão do que dá pra medir sem tocar na view proibida) | 7-9 round-trips seriais (permission cache-hit=0, get_by_channel_id x2, get_panel, ensure_staff, claim_ticket ~5 statements, log_service ~3, audit_log_service ~3) | **5-7** (ensure_staff cacheado na maioria dos cliques; get_panel e a 2ª leitura de ticket seguem pendentes — arquivo proibido, ver seção 7) | 1 (defer) + 1 (followup) — inalterado | Redução real hoje: ensure_staff. Redução adicional (get_panel cache, eliminar 2ª leitura, log em background) depende do patch na view — seção 7 |

Com `RTT_assumido = 80ms` (meio da faixa citada): a query eliminada por mensagem em canal comum representa **~80ms a menos por mensagem, em todo canal não-ticket do servidor** — o maior ganho agregado desta fase, porque roda com frequência muito maior que qualquer clique de botão. `ensure_staff` cacheado economiza ~160ms (SELECT+COMMIT) na maioria dos cliques de Assumir/Liberar.

---

## 4. Funcionalidades preservadas

- Nenhuma mensagem, nenhuma condição de erro, nenhuma regra de negócio mudou.
- `get_by_channel_id` continua retornando dado 100% fresco sempre que o ticket existe — só o caso "não existe" é cacheado, e é seguro por construção (channel_id de ticket nunca é reciclado).
- `ensure_staff` continua criando staff novo e atualizando `display_name` quando muda — só evita o round-trip quando não há nada para atualizar E o cache ainda é válido (120s).
- `log_service.record`/`audit_log_service.record` **não mudaram** — só ganharam um método irmão opt-in. Nenhum dos ~30+60 chamadores existentes foi tocado.
- `record_first_message` (método antigo) foi mantido intacto, só deixou de ser chamado pelo listener (que agora usa a versão combinada).
- Nenhum arquivo da lista proibida foi editado.
- Nenhuma migration criada/editada.

---

## 5. Testes executados

### Baseline (antes das mudanças)
```
./venv/Scripts/python.exe -m pytest -q --ignore=tests/test_auth_routes.py --ignore=tests/test_auth_service.py --ignore=tests/test_internal_routes.py --ignore=tests/test_jwt_service.py --ignore=tests/test_launcher_download_routes.py
4 failed, 264 passed, 6 warnings, 14 errors in 5.01s
```
(os 5 arquivos ignorados falham na coleta por `ModuleNotFoundError: httpx`/`jwt` — dependências ausentes neste venv, não relacionado a esta auditoria; os 4 failed e 14 errors são os mesmos já documentados em `docs/AUDITORIA_PERFORMANCE.md` — Fase 0/Fase 4 — como pré-existentes e não relacionados a performance: `AuditLogCategory.GIVEAWAY` faltando nos mapas de label/cor/target_kind, e 14 testes de `test_audit_fixes_validation.py` que exigem Postgres real + `JWT_SECRET_KEY`.)

### Depois das mudanças
```
./venv/Scripts/python.exe -m pytest -q --ignore=tests/test_auth_routes.py --ignore=tests/test_auth_service.py --ignore=tests/test_internal_routes.py --ignore=tests/test_jwt_service.py --ignore=tests/test_launcher_download_routes.py
4 failed, 275 passed, 6 warnings, 14 errors in 7.70s
```
Mesmos 4 failed, mesmos 14 errors (pré-existentes, confirmados idênticos por nome de teste). **+11 passed** = os 11 testes novos de `tests/test_perf_audit_2.py`, todos verdes. Sem regressão.

### `tests/test_perf_audit_2.py` isolado
```
11 passed in 2.76s
```
Cobre: cache negativo de canal (hit/miss/`forget_channel`), não-cache de ticket existente (sempre fresco), sessão única em `record_first_message_for_channel` (ticket existente e canal já confirmado como não-ticket), cache de `ensure_staff` (hit e invalidação por mudança de nick), `record_background` de `LogService`/`AuditLogService` (dispara e não bloqueia; engole exceção sem propagar), cache+invalidação de `get_evaluation_settings`.

### Lint / compile
```
ruff check <arquivos tocados>: All checks passed!
ruff check . (repo inteiro): 33 erros — nenhum nos arquivos tocados por esta fase (confirmado isolando os 9 arquivos); os 33 são pré-existentes/de outro trabalho em paralelo (ex.: SIM105 em views não tocadas aqui)
py_compile <arquivos tocados>: OK
```

---

## 6. Riscos

- **Cache negativo de canal (`_confirmed_non_ticket_channels`) é em memória de processo, por instância do bot.** Se o bot rodar com múltiplas instâncias/processos (não é o caso hoje — `core/bot.py` é singleton por deploy), cada processo teria seu próprio cache; sem problema de consistência (é só otimização local), mas sem efeito cross-processo.
- **Cache de `ensure_staff` (120s) e dos 4 novos `get_*_settings` (300s) podem mostrar dado levemente desatualizado** dentro da janela de TTL — mesma classe de risco já aceita pelos 4 caches equivalentes que já existiam antes desta fase (`get_settings`, `get_ticket_settings`, `get_permission_settings`, `get_anti_spam_settings`). Nenhum dado de status/claim de ticket foi cacheado (isso foi propositalmente evitado, conforme pedido).
- **`record_background` (log/audit log) foi só adicionado, não conectado a nenhum chamador ainda** (a view que se beneficiaria está sendo reescrita em paralelo). Zero risco por não estar em uso, mas também zero ganho até alguém trocar `await bot.log_service.record(...)` por `bot.log_service.record_background(...)` nos pontos certos (ver seção 7).
- **`forget_channel` é chamado para TODO canal deletado**, não só tickets — isso é intencional (mantém o cache limitado ao nº de canais vivos), mas significa que descartar a entrada de um canal que nunca foi ticket é um no-op barato (não é um bug, só uma nota).

---

## 7. Recomendações pendentes (arquivos proibidos — não aplicadas, patch sugerido para aplicação manual)

### 7.1 `views/ticket_actions_view.py` — `claim()`: usar o cache de staff, eliminar a 2ª leitura de ticket, mover log pra background

O método `claim()` (lido nesta auditoria, antes de qualquer edição paralela) fazia:

```python
staff = await bot.staff_service.ensure_staff(guild.id, member.id, member.display_name)
try:
    await bot.claim_service.claim_ticket(interaction.channel_id, staff.id)
except ClaimError as exc:
    await interaction.followup.send(str(exc), ephemeral=True)
    return

ticket = await bot.ticket_service.get_by_channel_id(interaction.channel_id)  # <-- 2ª leitura, redundante
await bot.log_service.record(
    guild_id=guild.id,
    action=LogAction.CLAIM,
    actor_discord_id=member.id,
    staff_id=staff.id,
    ticket_id=ticket.id if ticket else None,
    category_snapshot=ticket.category.value if ticket else None,
    message=f"{member} assumiu o ticket.",
)
await bot.painel_service.refresh_dashboard(guild.id)
await interaction.followup.send(f"{member.mention} assumiu este ticket.", ephemeral=False)
```

`ensure_staff` já ganhou cache nesta fase (aplicado em `services/staff_service.py`) — nenhuma mudança necessária aqui, o ganho já existe automaticamente.

Patch sugerido para a 2ª leitura + log:

```python
# claim_service.claim_ticket já carregou e travou o Ticket na mesma
# transação — devolver o snapshot que a view precisa (id + category) evita
# reabrir uma 3a/4a sessão só pra reler o mesmo registro.
# Opção A (menor risco, sem mudar assinatura do ClaimService): manter a
# releitura, mas trocar log_service.record por record_background (já pronto,
# aditivo, nao muda nada em quem ainda chama record()):

    ticket = await bot.ticket_service.get_by_channel_id(interaction.channel_id)
    bot.log_service.record_background(
        guild_id=guild.id,
        action=LogAction.CLAIM,
        actor_discord_id=member.id,
        staff_id=staff.id,
        ticket_id=ticket.id if ticket else None,
        category_snapshot=ticket.category.value if ticket else None,
        message=f"{member} assumiu o ticket.",
    )
    await bot.painel_service.refresh_dashboard(guild.id)
    await interaction.followup.send(f"{member.mention} assumiu este ticket.", ephemeral=False)
```

Mesmo patch para `unclaim()` (troca `await bot.log_service.record(...)` por `bot.log_service.record_background(...)`, sem `await`).

Para `close()`: mesma troca (`log_service.record` -> `record_background`), mas **com cuidado**: `close()` usa o resultado de `bot.ticket_service.close_ticket(...)` (que já tem `ticket.category`), então nem precisa de releitura — só trocar a chamada de log por `record_background` já elimina o bloqueio, sem tocar em mais nada.

**Opção B (ganho maior, risco maior — requer mudar `ClaimService`)**: fazer `claim_ticket`/`unclaim_ticket` devolverem também `ticket_id`/`category` (ex.: um dataclass `ClaimResult` em vez de `Claim` puro), eliminando a releitura de vez. Não recomendado aplicar junto com a reescrita paralela da view — mudar a assinatura de um serviço que a view (em reescrita concorrente) já chama é o tipo de conflito que a regra do escopo pediu pra evitar. Se quiser esse ganho adicional, aplicar depois que a reescrita da view mesclar, coordenando os dois lados.

### 7.2 `views/ticket_actions_view.py` — `create_voice_channel()`: mover `get_settings` pra fora do caminho síncrono já é módico (já é cache-hit via `ConfigService`), o gargalo real ali é a chamada de rede ao Discord (`guild.create_voice_channel`) — não há round-trip de banco a cortar, é I/O de API externa inerente à ação. Nenhuma mudança recomendada além do que `RELATORIO_DEFER_3S.md` já cobriu (defer primeiro).

### 7.3 `services/ticket_panel_service.py` — cache de `get_panel(panel_id)`

```python
# get_panel_for_ticket -> get_panel(panel_id) é chamado em TODO claim/unclaim
# (via member_matches_panel_claim_roles) e não tem cache, ao contrário de
# guild_settings/ticket_settings/permission_settings/anti_spam (ConfigService).
# TicketPanel muda raramente (só via /painel-setup ou telas de edição de
# painel) — candidato natural a TTLCache, mesmo padrão de config_service.py.

_PANEL_CACHE_TTL_SECONDS = 300.0

class TicketPanelService:
    def __init__(self, database: Database) -> None:
        self._database = database
        self._panel_cache: TTLCache[uuid.UUID, TicketPanel] = TTLCache(_PANEL_CACHE_TTL_SECONDS)

    async def get_panel(self, panel_id: uuid.UUID) -> TicketPanel | None:
        cached = self._panel_cache.get(panel_id)
        if cached is not None:
            return cached
        async with self._database.session() as session:
            panel = await TicketPanelRepository(session).get_by_id(panel_id)
        if panel is not None:
            self._panel_cache.set(panel_id, panel)
        return panel

    # em TODO metodo que faz UPDATE/DELETE de um TicketPanel (criar/editar/
    # excluir painel, trocar cargos de claim, etc.) adicionar:
    #     self._panel_cache.invalidate(panel_id)
    # logo apos o commit.
```

Isso elimina 1 round-trip a mais no `claim()` (a chamada `get_panel_for_ticket`) na maioria dos cliques, sem risco de dado desatualizado relevante (painel muda raramente, e uma janela de 300s de defasagem no filtro de cargo que pode assumir é aceitável — a permissão "quem pode assumir" continua sendo revalidada por `member_can`/`member_matches_panel_claim_roles` a cada clique, só a leitura do painel em si fica em cache).

**Cuidado ao aplicar**: `services/ticket_panel_service.py` tem muitos pontos de escrita (`review_ticket`, criação/edição de painel, etc.) — cada um precisa da chamada de `invalidate` correspondente. Recomendo aplicar isso só depois que a reescrita paralela do arquivo estabilizar, e então mapear TODOS os `session.add`/mutação de `TicketPanel` pra garantir que nenhuma escrita fique sem invalidação (uma invalidação esquecida serviria dado desatualizado por até 5 minutos).

### 7.4 Índices — nenhum novo recomendado nesta fase

A Fase 3 anterior (`alembic/versions/15cdb4300d1a_indices_compostos_hot_paths.py`) já cobriu os hot paths de tickets/punishments/subscriptions/payment_history/verification_sessions/partnerships com índices compostos/parciais desenhados a partir de chamadores reais. Esta fase não identificou nenhuma query nova sem índice — o gargalo restante era número de round-trips, não plano de query (RTT domina sobre tempo de execução em tabelas pequenas, conforme já documentado na Fase 3).

### 7.5 `database/database.py` — `pool_recycle` (avaliado, não aplicado)

`pool_pre_ping=True` já está ativo (testa a conexão a cada checkout, absorvendo desconexões silenciosas do pooler do Supabase) e `statement_cache_size=0` já está correto para pgbouncer em modo transação. Considerar `pool_recycle=1800` (recicla conexões com mais de 30min, proativo em vez de reativo) é uma prática comum com pgbouncer, mas como `pool_pre_ping` já cobre o caso reativo e não há evidência concreta (log de erro de conexão stale) de que isso seja necessário aqui, não foi aplicado — para não mudar comportamento de pool sem sinal real do problema. Se aparecerem erros esporádicos de conexão "stale"/"terminated" em produção, esse é o próximo ajuste a testar:

```python
self._engine: AsyncEngine = create_async_engine(
    database_url,
    echo=echo,
    pool_pre_ping=True,
    pool_size=pool_size,
    max_overflow=max_overflow,
    pool_recycle=1800,  # novo — reciclagem proativa, defensivo contra pgbouncer
    connect_args={"statement_cache_size": 0},
)
```

### 7.6 `core/bot.py` — `tree.sync()` incondicional no boot (M8 da auditoria anterior, ainda pendente)

Não aplicado nesta fase (fora do caminho crítico de latência por clique, que era o foco pedido; e a lógica de "sincronizar só quando o command tree mudou" precisa de um hash/diff confiável para não arriscar comandos desatualizados — risco médio, merece uma fase própria). Mantido como pendência já registrada.
