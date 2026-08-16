# Benchmark de latência — Sistema de Tickets (BOT LIMERENCE)

Data: 2026-08-16
Escopo original (seções 0-11 abaixo): **diagnóstico apenas**, nenhuma linha de
código de produção alterada. A seção 12 (adicionada depois, mesma data)
documenta a otimização cirúrgica feita **a partir** destes achados — só as
duas correções comprovadas por este benchmark, nenhuma especulação nova.
Nenhum commit foi feito em nenhuma das duas etapas.

---

## 0. Limitação honesta do ambiente

Este ambiente **não tem** um bot Discord real conectado (sem token/gateway) nem
um Postgres real acessível (`localhost:5432` recusa conexão; sem Docker daemon
disponível). Isso significa que **não é possível medir**, de forma real, neste
ambiente:

- latência de rede até o Postgres gerenciado (Supabase, via pooler);
- latência de rede até a API do Discord (defer, edit, set_permissions, send).

Diante disso, esta auditoria separa rigorosamente dois tipos de dado:

- **MEDIDO** — número obtido de execução real, reprodutível, deste ambiente.
- **ESTRUTURAL** — fato obtido por leitura de código (contagem de round-trips,
  presença/ausência de lock, chamadas síncronas), 100% verificável, mas não é
  um tempo em ms.
- **HIPÓTESE** — não medido aqui; citado só como referência de ordem de
  grandeza documentada publicamente, nunca como número específico inventado.

O que **foi possível medir de verdade**: o overhead de Python + SQLAlchemy ORM
que o próprio bot paga, isolando a variável de rede — rodando os mesmos
services de produção (`TicketService`, `ClaimService`, `StaffService`,
`LogService`, `AuditLogService`) contra SQLite em memória (mesmo processo, sem
rede), via um script descartável fora do repositório
(não commitado, não faz parte da suite de testes). Isso é um **piso**: o tempo
real em produção via Supabase/pgbouncer é sempre maior que isto, porque soma
RTT de rede que aqui é ~0.

---

## 1. Resumo

A operação estruturalmente mais cara do fluxo de Tickets é **Assumir**
(`claim`): é a única que soma round-trip de permissão + 2 leituras de ticket +
2 leituras de painel (uma duplicada, achado novo desta auditoria) + sessão de
claim com ~5 statements + log em background + 2 chamadas à API do Discord
(edição do embed do painel + followup). As demais (Liberar/Incluir/
Remover/Fechar) são subconjuntos do mesmo padrão, com Incluir/Remover tendo um
achado próprio (auditoria síncrona bloqueando a resposta final — seção 6.2).

**O banco (SQLite local) não é o gargalo de tempo de execução** — todas as
operações mediram abaixo de ~9ms mesmo com todos os round-trips somados. Isso
não prova que o Postgres real também é rápido (falta o RTT de rede real), mas
prova que **o overhead de ORM/Python do bot em si é pequeno** — o peso real,
se houver, está no RTT de rede (Supabase e/ou Discord), não no código.

---

## 2. Tabela — medições locais (SQLite em memória, N=10, sem rede)

| Operação | Mín | Máx | Média | Mediana | P95 |
|---|---|---|---|---|---|
| `get_by_channel_id` (ticket existe, sempre fresco) | 0.73ms | 4.16ms | 1.31ms | 1.01ms | 4.16ms |
| `get_by_channel_id` (canal comum, 1ª vez = miss) | 0.87ms | 0.87ms | 0.87ms | 0.87ms | 0.87ms |
| `get_by_channel_id` (canal comum, cache negativo hit) | 0.00ms | 0.00ms | 0.00ms | 0.00ms | 0.00ms |
| `ensure_staff` (1ª vez = cache miss + INSERT) | 8.11ms | 8.11ms | 8.11ms | 8.11ms | 8.11ms |
| `ensure_staff` (cache hit, nick igual) | 0.00ms | 0.06ms | 0.01ms | 0.00ms | 0.06ms |
| `claim_service.claim_ticket` (sessão completa, ~5 statements+commit) | 4.27ms | 8.31ms | 5.15ms | 4.77ms | 8.31ms |
| `claim_service.unclaim_ticket` (sessão completa) | 3.89ms | 8.23ms | 5.14ms | 4.67ms | 8.23ms |
| `log_service.record()` — `await` direto (bloqueia) | 2.62ms | 11.61ms | 4.45ms | 3.63ms | 11.61ms |
| `log_service.record_background()` — só o retorno da chamada | 0.00ms | 0.02ms | 0.01ms | 0.00ms | 0.02ms |

Script: benchmark descartável, não versionado no repositório
(`bench_tickets.py`, no scratchpad da sessão). Reproduzível: cria as tabelas
reais (`Ticket`, `Claim`, `Staff`, `StaffStats`, `StaffActivity`, `LogEntry`,
`GuildSettings`, `AuditLogSettings`, `AuditLogEntry`) via `Base.metadata` num
engine `sqlite+aiosqlite:///:memory:`, injeta esse engine no lugar de
`database.database.Database` (mesma interface pública, `.session()`) e chama
os métodos de produção sem alterar nenhum deles. Dependência `aiosqlite`
instalada só no venv local, não adicionada a `requirements*.txt`.

**Achado confirmado por medição**: `record_background()` retorna em média
**~833x mais rápido** que `record()` aguardado direto (0.01ms vs 4.45ms neste
ambiente) — a chamada de fato não bloqueia o caminho de resposta ao usuário. O
trabalho de banco real (INSERT + possível `channel.send`) roda depois, numa
`asyncio.Task` rastreada. Confirma que o patch já aplicado em
`views/ticket_actions_view.py` (claim/unclaim/fechar) está funcionando como
projetado.

---

## 3. Breakdown estrutural por operação (contagem de round-trips/chamadas, não tempo)

Convenção: "DB" = 1 ida-e-volta de rede ao Postgres (1 SELECT/INSERT/UPDATE/
COMMIT isolado); "Discord" = 1 chamada HTTP à API do Discord. Fonte: leitura
direta do código atual (`views/ticket_actions_view.py`, linhas indicadas).

### 3.1 Assumir (`claim`, linhas 118-162)

```
member_can(...)                                    Discord: 0   DB: 0-1 (cache 300s, permission_settings)
interaction.response.defer()                       Discord: 1
get_by_channel_id(...)                    linha 131 DB: 1        (SEMPRE fresco, nunca cacheado — correto)
get_panel_for_ticket(...)                 linha 132 DB: 0-1      (só se ticket.panel_id setado; SEM cache)
ensure_staff(...)                         linha 140 DB: 0-2      (cache 120s — 0 na maioria dos cliques)
claim_ticket(...)                         linha 142 DB: ~5-6     (1 sessão: SELECT FOR UPDATE, has_prior_claim,
                                                                   INSERT claim, get_or_create stats, log_event, COMMIT)
get_by_channel_id(...)                    linha 147 DB: 1        (2ª leitura do MESMO ticket — duplicada, achado
                                                                   já documentado em AUDITORIA_PERFORMANCE_2.md §7.1,
                                                                   não corrigido nesta tarefa por ser diagnóstico)
log_service.record_background(...)        linha 150 DB: 0        (não bloqueia — confirmado por medição, seção 2)
painel_service.refresh_dashboard(...)     linha 159 Discord: 0   (já fire-and-forget, confirmado em
                                                                   services/painel_service.py:53-61)
_refresh_panel_message(...)               linha 161:
  ├─ get_panel_for_ticket(...)              linha 80 DB: 0-1      (⚠ NOVO ACHADO — ver seção 4.1)
  └─ message.edit(embed, view)              linha 87 Discord: 1
interaction.followup.send(...)            linha 162 Discord: 1
```

**Total round-trips DB no caminho síncrono (painel-based, staff em cache):**
1 + 1 + 0 + ~6 + 1 + 1 = **~10** round-trips seriais.
**Total chamadas Discord no caminho síncrono:** defer(1) + edit(1) + followup(1) = **3**.

### 3.2 Liberar (`unclaim`, linhas 171-201)

Mesmo padrão do Assumir, **sem** o `get_panel_for_ticket` de linha 132 (unclaim
não checa cargo restrito de painel) — só o de dentro de `_refresh_panel_message`.
**Total DB: ~9. Total Discord: 3.**

### 3.3 Fechar (`close`, linhas 248-317)

```
member_can/defer                                    Discord: 1 (response.defer, sem thinking)
get_by_channel_id(...)                    linha 260 DB: 1
staff_service.get_by_id(...)              linha 280 DB: 1        (sem cache — get_by_id não usa o TTLCache
                                                                   de ensure_staff, que é por (guild,discord_id))
ConfirmCloseView (espera clique do usuário)          Discord: 2  (followup do modal de confirmação + espera humana)
close_ticket(...)                         linha 285 DB: ~4-5     (1 sessão: UPDATE ticket, leituras de stats/
                                                                   achievements, COMMIT)
_refresh_panel_message(..., disabled=True) linha 291:
  ├─ get_panel_for_ticket(...)                       DB: 0-1
  └─ message.edit(...)                               Discord: 1
log_service.record_background(...)        linha 298 DB: 0        (não bloqueia)
painel_service.refresh_dashboard(...)     linha 306 Discord: 0
voice_channel.delete() (se existir)       linha 312 Discord: 0-1
channel.send(embed fechado + view)        linha ~320 Discord: 1
```

**Nota:** `close()` **espera o clique humano** no `ConfirmCloseView` antes de
prosseguir (`await confirm_view.wait()`) — isso não é latência de sistema, é
tempo de decisão do usuário, mas infla qualquer medição "ponta a ponta" feita
por observação externa (ex.: cronômetro manual). Separar isso é essencial pra
não atribuir ao bot um atraso que é do humano decidindo.

### 3.4 Incluir / Remover (`_IncludeUserSelect`/`_RemoveUserSelect`, linhas 369-479)

```
interaction.response.defer(...)                     Discord: 1
get_by_channel_id(...)                               DB: 1
channel.set_permissions(...)                         Discord: 1
audit_log_service.record(...)             linha 404 DB: 1-2      (⚠ SÍNCRONO — ver achado 4.2)
channel.send(...)                         linha 414 Discord: 1
interaction.followup.send(...)            linha 417 Discord: 1
```

### 3.5 Criar Ticket (`TicketPanelService.open_ticket`, linhas 586-660+)

```
check_can_open(...)                       linha 618:
  ├─ get_ticket_settings(...)                        DB: 0-1 (cache 300s)
  └─ count_open_by_member(...)                       DB: 1   (sempre fresco — correto, é um limite)
get_settings(...)                         linha 623  DB: 0-1 (cache 300s)
create_ticket(...)                        linha 634:
  ├─ guild.create_text_channel(...)                   Discord: 1  (cria canal + overwrites — chamada mais
                                                                    pesada de toda a operação, inerente à
                                                                    ação, não é round-trip de banco)
  └─ INSERT Ticket                                    DB: 1
ticket_channel.send(embed + view)                     Discord: 1
save_form_responses (se houver formulário)            DB: 0-1 (N inserts, N = perguntas do form, máx 5)
interaction.followup.send(...)                        Discord: 1
_notify_alert_channel(...) (se configurado)            Discord: 0-1
audit_log_service.record(...)                          DB: 1-2  (roda DEPOIS do followup.send — não
                                                                   atrasa a resposta percebida)
```

---

## 4. Gargalos secundários (achados novos desta auditoria, estruturais, não corrigidos)

### 4.1 `get_panel_for_ticket` chamado 2x em `claim()` — sem cache

`views/ticket_actions_view.py:132` (checagem de cargo restrito do painel) e
`views/ticket_actions_view.py:80` (dentro de `_refresh_panel_message`, chamada
pela reconstrução do embed) chamam `bot.ticket_panel_service.get_panel_for_ticket`
de forma independente, na mesma execução de `claim()`. `get_panel()`
(`services/ticket_panel_service.py:154-156`) não tem cache — confirmado por
leitura direta:

```python
async def get_panel(self, panel_id: uuid.UUID) -> TicketPanel | None:
    async with self._database.session() as session:
        return await TicketPanelRepository(session).get_by_id(panel_id)
```

Isso é **2 round-trips DB idênticos na mesma interação**, em servidores que
usam painel configurável (o cenário que o redesign de Tickets foi feito para
incentivar). Antes do redesign do painel (que introduziu `_refresh_panel_message`),
só existia 1 chamada. Este é o mesmo `get_panel` já apontado como candidato a
cache em `AUDITORIA_PERFORMANCE_2.md §7.3` — agora com **evidência adicional**
de que o redesign aumentou a frequência do problema (2x por claim em vez de 1x).
**Não corrigido nesta tarefa** (diagnóstico apenas, e a correção completa exige
mapear todos os pontos de escrita de `TicketPanel` para invalidação — trabalho
de fase própria, conforme já recomendado).

### 4.2 `audit_log_service.record()` síncrono antes do `followup.send()` em Incluir/Remover

`views/ticket_actions_view.py:404` (Incluir) e o equivalente em `_RemoveUserSelect`
chamam `await bot.audit_log_service.record(...)` — **não** `record_background()`
— antes de `channel.send()` e `interaction.followup.send()`. Isso significa que
Incluir/Remover pagam 1 sessão de banco completa (SELECT settings + INSERT +
COMMIT) **no caminho síncrono**, ao contrário de claim/unclaim/fechar (que já
usam `record_background()` para o `log_service`). `record_background()` existe
em `AuditLogService` também (`services/audit_log_service.py:249-260`, mesmo
padrão), mas não foi conectado aqui. Estrutural, não medido em produção — mas
o comportamento é idêntico ao já medido para `log_service.record()` (seção 2):
uma sessão de banco síncrona custa, neste ambiente local, ~2.6-11.6ms; em
produção via Supabase, o custo real depende do RTT de rede não medido aqui.

### 4.3 `staff_service.get_by_id()` sem cache, usado em `close()`

`views/ticket_actions_view.py:280` usa `bot.staff_service.get_by_id(...)`, que
é uma consulta direta sem cache (`services/staff_service.py:64-66`), diferente
de `ensure_staff` (que tem TTLCache de 120s por `(guild_id, discord_user_id)`).
`get_by_id` busca por `staff.id` (UUID interno), não por `discord_user_id` —
não dá pra reaproveitar o mesmo cache sem uma chave adicional. Estrutural,
baixo impacto (só acontece 1x por fechamento, não por clique repetido).

---

## 5. Locks (medido estruturalmente — grep no repositório inteiro)

```
grep -rn "asyncio.Lock\|Semaphore" services/ views/ cogs/ utils/ core/
```

Resultado: **nenhum** `asyncio.Lock`/`Semaphore` relacionado a tickets, claim
ou canais. Os únicos locks do projeto são: `services/auth_service.py` (login),
`services/reconciliation_service.py` (reconciliação de licenças, já documentada
como corrigida em fase anterior — semáforo por guild, não global),
`cogs/verification.py` (limite de entradas simultâneas no captcha), e
`core/rate_limiter.py`. **Nenhum deles é acionado pelo fluxo de Tickets.**

A única forma de serialização em `claim_ticket` é um lock **de linha** do
Postgres (`SELECT ... FOR UPDATE`, `database/repositories/ticket_repository.py:20-25`,
usado em `services/claim_service.py:29`) — trava **só a linha daquele ticket
específico**, durante a transação daquele claim. Isso significa:

```
Ticket A sendo assumido → trava só a linha do Ticket A
Ticket B sendo assumido ao mesmo tempo → NÃO espera Ticket A
```

**Conclusão: não existe fila global.** Dois staffs assumindo tickets
diferentes ao mesmo tempo não competem entre si. Só duas pessoas tentando
assumir o **mesmo** ticket ao mesmo tempo serializam (correto e necessário,
é a proteção contra dupla-assumida pedida no redesign original).

---

## 6. Event loop bloqueado (medido estruturalmente)

```
grep -rn "time\.sleep\|requests\.(get|post|put|delete)" \
  services/ticket_service.py services/claim_service.py services/staff_service.py \
  services/log_service.py services/audit_log_service.py services/ticket_panel_service.py \
  views/ticket_actions_view.py views/ticket_closed_view.py views/ticket_panel_open_view.py \
  cogs/tickets.py utils/transcript.py utils/ticket_lifecycle.py
```

Resultado: **nenhuma ocorrência** em nenhum desses 12 arquivos (todo o
caminho crítico de Tickets + geração de transcrição). A única operação
potencialmente pesada de CPU do sistema de Tickets, geração de PDF de
transcrição (`utils/transcript.py:_render_pdf`), já roda em thread separada
via `asyncio.to_thread` (confirmado por leitura — não é tocada nesta tarefa,
já estava correto).

---

## 7. Chamadas à API do Discord — HIPÓTESE, não medido

Não há bot conectado a um gateway real neste ambiente, então **nenhum tempo em
ms de chamada Discord foi medido**. O que se sabe com certeza (estrutural,
seção 3): Assumir/Liberar fazem 3 chamadas Discord no caminho síncrono
(defer + edit + followup); Fechar faz ~5-6 (incluindo a espera humana do
modal de confirmação, que não é latência de sistema); Incluir/Remover fazem 4.

É publicamente documentado que a API do Discord aplica rate limiting por rota
e que o SLA de resposta a uma interação é de até 3000ms para o ACK inicial —
isso é comportamento da plataforma, não algo que o bot controla, e não deve
ser confundido com "o bot está lento". **Nenhum número específico de latência
de rede do Discord é apresentado aqui** por não ter sido medido.

**Recomendação para medição real futura**: rodar o bot num ambiente com
gateway conectado e instrumentar `discord.py` (que já expõe `bot.latency`,
a latência do heartbeat do gateway) mais um `timed_step` ao redor de cada
`interaction.response.defer/edit_original_response/followup.send` real — não
implementado aqui por não haver conexão real disponível.

---

## 8. Critério de sucesso — resposta objetiva

> "Por que o botão Assumir está demorando?"

**Resposta com os dados disponíveis neste ambiente:**

```
O overhead de Python/ORM do bot (medido, local, sem rede) é pequeno:
  DB (get_by_channel_id + get_panel + ensure_staff + claim_ticket + 2ª leitura): ~1+1+0+5+1 ≈ 8ms (piso local)
  log_service.record_background(): ~0ms (não bloqueia, confirmado)

O bot faz ~10 round-trips seriais ao banco e 3 chamadas à API do Discord
no caminho síncrono de Assumir. Em produção (Supabase via pooler + rede real
até o Discord), CADA round-trip soma o RTT real de rede, não medido aqui —
esse é o componente que domina o tempo total percebido, não a lógica Python
em si (que aqui ficou na casa de milissegundos de dígito único a duas
dezenas).

Não é possível, neste ambiente, dizer com números reais se o gargalo em
produção é o Postgres ou o Discord — ambos estão fora do alcance de medição
aqui. O que ESTE benchmark prova é que a lógica do bot não é o problema:
mesmo somando todos os round-trips estruturais, o tempo de CPU/ORM é da ordem
de milissegundos de um dígito, não segundos.

Se a lentidão percebida em produção for de segundos (conforme relatado pelo
usuário), ela quase certamente vem do RTT de rede acumulado ao longo dos ~10
round-trips seriais ao banco (não paralelizáveis sem redesenhar o serviço,
ver AUDITORIA_PERFORMANCE_2.md §7.1) e/ou das 3 chamadas sequenciais à API do
Discord — não da lógica de negócio em si.
```

---

## 9. Recomendações (NÃO aplicadas — diagnóstico apenas)

1. **Cache de `get_panel(panel_id)`** (`services/ticket_panel_service.py`) —
   já recomendado em `AUDITORIA_PERFORMANCE_2.md §7.3`, agora com evidência
   de que elimina **2** round-trips por claim, não 1 (achado 4.1). Continua
   exigindo mapear todos os pontos de escrita de `TicketPanel` para
   invalidação — fase própria.
2. **Trocar `audit_log_service.record` → `record_background`** em
   `_IncludeUserSelect`/`_RemoveUserSelect` (achado 4.2), mesmo padrão já
   aplicado em claim/unclaim/fechar. Baixo risco (método já existe, já
   testado), mas está fora do escopo desta tarefa (diagnóstico).
3. **Medição real de RTT de rede** — só é possível com bot conectado a um
   gateway real e Postgres real acessível. Nenhuma das duas condições existe
   neste ambiente. Se possível rodar em staging com esses dois disponíveis,
   repetir este benchmark substituindo o `_SqliteDatabase` do script por
   `Database` real e capturando `interaction` reais.

---

## 10. Testes

Nenhum arquivo de produção foi alterado nesta tarefa — só leitura de código e
um script de benchmark descartável fora do repositório. Suite completa
executada antes e depois (idêntica, nenhuma mudança de código):

```
4 failed, 355 passed, 7 warnings
```

As 4 falhas são as mesmas já documentadas em tarefas anteriores (categoria
`giveaway` ausente em `AUDIT_CATEGORY_*`, contagem de botões de help) — não
tocadas, não mascaradas.

---

## 11. Confirmação — nada foi alterado nesta tarefa

```
git status --short (arquivos de código) — idêntico ao estado anterior à
                                            execução desta tarefa
```

`TicketActionsView`, `TicketPanelService`, `TicketPanelOpenView`,
`TicketPanelsView`, `TicketClosedView`, `database/database.py`, `core/bot.py`
— nenhum foi editado. `custom_id`, permissões, fluxo de claim/unclaim,
fechamento, transcrição, logs, configuração e export/import continuam
exatamente como estavam ao final da tarefa anterior.

---

## 12. Otimizações aplicadas após benchmark

Nesta etapa, **só** os dois problemas concretos apontados nas seções 4.1 e 4.2
foram corrigidos. Nada especulativo. Único arquivo tocado: `views/ticket_actions_view.py`.
`TicketPanelService`, `TicketPanelOpenView`, `TicketPanelsView`,
`TicketClosedView`, `embeds.py`, `painel_view.py`, `ticket_settings.py`,
`database/database.py`, `core/bot.py`, `pool_recycle`, `tree.sync()` — **nenhum
tocado**, conforme pedido.

### 12.1 Chamada duplicada de `get_panel_for_ticket()` em `claim()` — eliminada

**Antes** (`views/ticket_actions_view.py`, achado 4.1 original):

```
claim()
 ├─ linha 144: panel = get_panel_for_ticket(existing)      ← DB round-trip #1
 └─ linha 161: _refresh_panel_message(...)
      └─ get_panel_for_ticket(ticket)                       ← DB round-trip #2 (MESMO painel)
```

**Depois**: `_refresh_panel_message` ganhou um parâmetro opcional `panel`
(sentinela `_PANEL_NOT_PROVIDED`, não um `None` ambíguo — um ticket sem painel
já é `None` legitimamente, então não dava pra usar `None` como "não
informado"). `claim()` passa o `panel` que já buscou na linha 144:

```python
await _refresh_panel_message(
    interaction, ticket, claimed_staff_name=member.display_name, panel=panel
)
```

Nenhuma informação foi perdida: `TicketPanel.panel_id` não muda depois que o
ticket é criado, então o painel buscado a partir de `existing` (ticket lido
ANTES do claim) continua sendo exatamente o mesmo painel do `ticket` (lido
DEPOIS do claim) — só o `status`/`claimed_by_staff_id` do ticket mudam entre
as duas leituras, nunca o `panel_id`.

`unclaim()` e `close()` **não foram alterados** — nenhum dos dois já tinha o
painel em mãos antes de chamar `_refresh_panel_message`, então continuam
buscando do jeito de sempre (parâmetro `panel` omitido = comportamento
idêntico ao anterior, é o valor default da função).

**Queries por clique em Assumir (painel configurável, caso mais comum do
redesign):** `get_panel_for_ticket` **2 → 1** chamada. Confirmado por teste
(`test_claim_calls_get_panel_for_ticket_only_once`, ver seção 12.3) que
verifica `await_count == 1` num mock do service.

### 12.2 `audit_log_service.record()` síncrono em Incluir/Remover — migrado pra `record_background()`

**Avaliação de segurança feita antes da troca** (pedido explícito da tarefa):

| Pergunta | Resposta |
|---|---|
| O log é crítico pra confirmar a operação? | Não — a operação (`channel.set_permissions`) já foi executada e confirmada (bloco `try/except discord.HTTPException`) **antes** da chamada de auditoria, nos dois casos. Se o log falhar, o acesso já foi concedido/revogado de qualquer forma — o log é só trilha. |
| A operação principal já foi persistida? | Sim — `set_permissions` é a mudança de estado real (permissão do canal Discord); não há escrita no Postgres cuja consistência dependa da auditoria. |
| O background logger trata exceções? | Sim — `AuditLogService.record_background` (`services/audit_log_service.py:249-260`, já existente, não tocado nesta tarefa) cria uma `asyncio.Task` rastreada num `set` (protegida contra coleta prematura pelo GC) e usa `_log_background_error` como `done_callback`, que loga com `logger.exception(...)` — nunca propaga pro chamador nem derruba o bot. Mesmo padrão já usado e testado em claim/unclaim/fechar. |
| O contexto necessário está disponível? | Sim — todos os kwargs (`guild_id`, `category`, `action`, `executor_id/name`, `target_id/name`, `details`) já são valores concretos no momento da chamada, não referências que precisem da `interaction` continuar viva depois. |
| O comportamento de auditoria permanece igual? | Sim — mesma categoria, mesma ação, mesmos campos; só passa a rodar depois de a interação já estar respondida em vez de antes. A entrada aparece no histórico de auditoria com uma defasagem de alguns ms, nunca é perdida (task rastreada, não fire-and-forget sem referência). |

**Decisão:** seguro migrar. `views/ticket_actions_view.py` linhas 422 e 499
(no diff anterior a esta etapa) trocadas de `await bot.audit_log_service.record(...)`
para `bot.audit_log_service.record_background(...)` (sem `await`) — mesmo
padrão exato de claim/unclaim/fechar. `channel.set_permissions` (a operação
que precisa terminar antes de confirmar sucesso) continua **inalterado**,
síncrono, antes de qualquer resposta ao usuário.

**Custo eliminado do caminho síncrono de Incluir/Remover:** 1 sessão de banco
completa (SELECT `audit_log_settings` + INSERT `audit_log_entries` + COMMIT).
Não há benchmark novo específico pra `AuditLogService` porque ela usa
**exatamente a mesma implementação** de `record_background`
(`asyncio.create_task` + task rastreada) já medida para `LogService` na seção
2 — o número já obtido (`record()` direto: média 4.45ms; `record_background()`:
média 0.01ms, ~833x mais rápido) se aplica igualmente aqui, por ser o mesmo
mecanismo, não uma extrapolação sobre um código diferente.

### 12.3 Testes criados

Novo arquivo `tests/test_ticket_actions_optimizations.py` — 6 testes, todos
verdes:

- `test_claim_calls_get_panel_for_ticket_only_once` — trava a regressão do
  achado 4.1: falha se alguém reintroduzir a segunda chamada.
- `test_claim_still_works_and_refreshes_panel_message` — claim continua
  funcionando (defer, log em background, edição do painel, resposta final).
- `test_claim_still_rejects_already_claimed_ticket_without_touching_panel_message`
  — concorrência: se `ClaimService` recusa (outro staff já assumiu), a
  mensagem do painel **não** é reeditada e o erro é mostrado — prova que a
  reutilização do `panel` não interfere na checagem de concorrência (que
  continua 100% dentro de `ClaimService.claim_ticket`, não tocado).
- `test_include_uses_record_background_not_record` — Incluir usa
  `record_background` e **nunca** `record` (`assert_not_awaited`); confirma
  que `set_permissions`/`channel.send`/`followup.send` continuam acontecendo.
- `test_remove_uses_record_background_not_record` — mesmo, pro fluxo de
  Remover.
- `test_remove_still_blocks_opener_and_admin_regardless_of_background_logging`
  — trava de proteção (não remover quem abriu o ticket) continua funcionando
  e, no caminho bloqueado, `record_background` **não** é chamado (nenhuma
  auditoria de uma ação que não aconteceu).

```
tests/test_ticket_actions_optimizations.py: 6 passed
Suite completa: 4 failed, 361 passed  (355 anterior + 6 novos; mesmas 4
                                        falhas pré-existentes, não mascaradas)
```

### 12.4 Mapeamento completo de `claim()` (pedido da tarefa, seção 4 — só mapa, sem mudança adicional)

| # | Operação | Query/chamada | Necessária? | Pode reutilizar dados? |
|---|---|---|---|---|
| 1 | `member_can` (via `_deny_if_cant`) | SELECT `permission_settings` | sim | cache `ConfigService` (300s) já usado — 0 round-trip na maioria |
| 2 | `interaction.response.defer()` | Discord API | sim (ACK obrigatório) | — |
| 3 | `get_by_channel_id(existing)` | SELECT `tickets` | sim | não — status/claim mudam a cada clique, precisa ser sempre fresco |
| 4 | `get_panel_for_ticket(existing)` | SELECT `ticket_panels` (se `panel_id` setado) | sim, se painel configurável | **agora sim** (12.1) — resultado passado pra `_refresh_panel_message` |
| 5 | `ensure_staff(...)` | SELECT (+ INSERT/UPDATE se novo/nick mudou) `staff` | sim | cache `StaffService` (120s) já usado — 0 round-trip na maioria |
| 6 | `claim_ticket(...)` | 1 sessão: `SELECT ... FOR UPDATE` + `has_prior_claim` (SELECT) + `INSERT claim` + `get_or_create stats` (SELECT/INSERT) + `log_event` (INSERT) + `COMMIT` | sim, é a operação central | não — cada statement tem propósito distinto (ver seção 12.5) |
| 7 | `get_by_channel_id(ticket)` — 2ª leitura | SELECT `tickets` | questionável | **não corrigido nesta etapa** — ver seção 12.5 |
| 8 | `log_service.record_background(...)` | background (não bloqueia) | sim, mas não no caminho síncrono | já otimizado (tarefa anterior) |
| 9 | `painel_service.refresh_dashboard(...)` | background (não bloqueia) | sim, mas não no caminho síncrono | já otimizado (tarefa anterior) |
| 10 | `_refresh_panel_message` → `_resolve_opener` | `guild.get_member` (local, sem rede) ou `bot.fetch_user` (Discord API, só se o membro saiu do servidor) | sim | já é o caminho mais barato possível |
| 11 | `_refresh_panel_message` → `message.edit(...)` | Discord API | sim (painel precisa refletir o novo estado) | — |
| 12 | `interaction.followup.send(...)` | Discord API | sim (resposta final) | — |

**Round-trips DB síncronos no caminho de Assumir, painel configurável, staff em
cache (caso mais comum):** antes desta etapa ≈ 1(#3) + 1(#4) + 0(#5, cache) +
~6(#6) + 1(#7) + 1(#4 duplicado) = **~10**. Depois desta etapa: mesma soma
**menos** o #4 duplicado = **~9**. Chamadas Discord síncronas: inalteradas, 3
(#2, #11, #12).

### 12.5 O que ainda resta (documentado, NÃO aplicado — fora do escopo cirúrgico desta tarefa)

- **Item #7 da tabela acima** — a 2ª leitura de `get_by_channel_id` depois do
  claim é tecnicamente evitável: `ClaimService.claim_ticket` já carrega o
  `Ticket` inteiro na linha 29 de `services/claim_service.py`
  (`ticket = await ticket_repo.get_by_channel_id_locked(channel_id)`), mas o
  método devolve só o `Claim`, não o `Ticket`. Eliminar essa releitura exigiria
  mudar a assinatura pública de `ClaimService.claim_ticket`/`unclaim_ticket`
  (ex.: devolver um dataclass com ambos) — isso é uma mudança de contrato de
  serviço, não uma otimização "cirúrgica" de 1 arquivo, e já foi sinalizado
  como "Opção B, risco maior" em `AUDITORIA_PERFORMANCE_2.md §7.1`. Não
  aplicado aqui por decisão explícita de manter o escopo mínimo.
- **Item #6** — os ~5 statements dentro de `claim_ticket` são todos
  necessários e sequenciais por natureza (o `SELECT FOR UPDATE` tem que vir
  primeiro pra travar a linha antes de qualquer leitura/escrita subsequente
  depender dela — não são paralelizáveis com segurança dentro da mesma
  transação, e a tarefa pediu explicitamente pra não introduzir race
  conditions). Nenhuma paralelização com `asyncio.gather` foi aplicada aqui.
- **`staff_service.get_by_id`** (usado em `close()`, achado 4.3 do benchmark)
  — sem cache, mas só roda 1x por fechamento (não por clique repetido) e usa
  uma chave diferente (`staff.id`, não `(guild_id, discord_id)`) do cache já
  existente de `ensure_staff` — não corrigido nesta etapa por ser uma chave de
  cache nova, não reaproveitamento do que já existe (a tarefa pediu
  explicitamente pra não criar outro cache).
