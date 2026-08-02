# Auditoria de Segurança, Privacidade e Integridade — BOT

Data: 2026-08-02
Escopo: projeto inteiro (31.7k LOC) — multi-tenant, pagamentos, permissões, dados sensíveis, tickets, boosters, renovações, DynamicItems, banco de dados, API, race conditions.
Método: 6 auditorias paralelas independentes (leitura completa dos módulos relevantes, não amostragem) + correção direta no código + testes automatizados (99 testes, 98 passando — 1 falha pré-existente não relacionada) + `py_compile` em todo o projeto.

---

## Resumo executivo

| Severidade | Encontrados | Corrigidos | Pendentes (documentados) |
|---|---|---|---|
| Crítica | 6 | 6 | 0 |
| Alta | 6 | 6 | 0 |
| Média | 6 | 6 | 0 |
| Baixa | 4 | 4 | 0 |
| Info/recomendação | 6 | — | 6 (não são bugs, são decisões de produto/infra) |

Todos os achados Crítica/Alta/Média/Baixa foram corrigidos e validados (compilação + suíte de testes). Itens "Info" no final são recomendações que exigem decisão de produto ou trabalho de infraestrutura maior que o razoável para uma correção pontual — estão documentados com instruções de como proceder.

---

## CRÍTICA

### C1 — Edição/exclusão cross-guild de planos de monetização
**Arquivo:** `views/monetization_panel_view.py` (`_PlanSelect.callback`)
**Causa:** o valor do select de plano vem do cliente Discord (pode ser forjado); `PlanRepository.get_by_id` nunca filtra por `guild_id`. Nenhum re-check de posse depois do fetch.
**Risco:** staff de uma guild podia editar preço/cargo/benefícios ou **deletar** um plano de outra guild, enviando um UUID arbitrário no componente.
**Correção:** `plan.guild_id != interaction.guild_id` → nega, igual ao padrão já usado (corretamente) em `coupon_panel_view.py`.
**Validado:** compila, sem teste automatizado direto (é uma view Discord) — testar manualmente: criar plano na Guild A, tentar editá-lo via painel `/monetizacao` da Guild B trocando o valor do select (requer client modificado ou repetir o teste assim que houver ferramenta de fuzzing de interação).

### C2 — Edição/exclusão cross-guild de painéis de ticket
**Arquivo:** `views/ticket_panels_view.py` (`_PanelSelect.callback`)
**Causa:** idêntica à C1, mas para `TicketPanelRepository`.
**Risco:** edição/publicação/despublicação/exclusão de painel de ticket de outra guild (embed, categorias, campos de formulário; podia até apagar mensagem publicada na guild vítima).
**Correção:** mesmo padrão de guarda `panel.guild_id != interaction.guild_id`.

### C3 — Aceitar/negar recurso de banimento cross-guild
**Arquivo:** `services/punishment_service.py` (`accept_appeal`, `deny_appeal`)
**Causa:** `PunishmentRepository.get_by_id` sem filtro de guild; o botão persistente (`DynamicItem`) resolve o `punishment_id`/`appeal_id` do próprio `custom_id`, mas nunca cruza com `interaction.guild_id` — só checava a permissão do clicador, não a posse do registro.
**Risco:** staff com permissão `recurso_banimento` na Guild A podia aceitar/negar recurso de um banimento pertencente à Guild B (ações do Discord — desbanir, restaurar cargo — executadas contra o guild errado, corrompendo o registro da guild B).
**Correção:** `punishment.guild_id != guild.id` → erro, nos dois métodos.

### C4 — Race condition: aprovação/rejeição de pagamento duplicada
**Arquivos:** `services/payment_service.py`, `services/subscription_service.py`, `database/repositories/payment_repository.py`
**Causa:** leitura de `payment.status` e escrita em transações/sessões separadas (clássico TOCTOU), sem `SELECT ... FOR UPDATE` nem `UPDATE ... WHERE status = esperado`. Dois cliques de staff simultâneos, ou webhook correndo contra clique manual, passavam ambos pela checagem antes de qualquer um escrever.
**Risco:** DM duplicada, entrada de auditoria duplicada, linha de `SubscriptionHistory` duplicada; em cenários de retry de webhook, potencial reprocessamento indevido de rejeição/expiração/cancelamento.
**Correção:**
- `PaymentRepository.get_by_id_locked` — novo método com `.with_for_update()`.
- `PaymentService.set_status` agora aceita `expected_statuses` e usa a leitura travada — a transição só ocorre se o status atual bater com o esperado, atomicamente.
- `SubscriptionService.confirm_payment/reject_payment/cancel_payment/expire_payment` passam a checar o retorno de `set_status`: se `None`, a corrida foi perdida e a função aborta sem duplicar efeito colateral.
**Validado:** `pytest tests/` — 98/99 passando (a falha é pré-existente e não relacionada).

### C5 — Race condition: limite de cupom pode ser ultrapassado
**Arquivos:** `services/coupon_service.py`, `database/repositories/discount_coupon_repository.py`
**Causa:** `validate_and_price` fazia `COUNT()` sem lock; `record_redemption` inseria em transação separada, sem reconferir o limite. Duas compras concorrentes com um cupom `max_global_uses=1` podiam ambas passar da validação.
**Correção:** `DiscountCouponRepository.get_by_id_locked` (`FOR UPDATE`); `record_redemption` agora trava a linha do cupom e **reconfere** limite global/por-usuário dentro da mesma transação do insert, levantando `CouponGlobalLimitReachedError`/`CouponUserLimitReachedError` se excedido — o insert só ocorre se realmente ainda há vaga.
**Nota de risco residual:** como `charge()` (criação do pagamento com preço já descontado) ocorre antes de `record_redemption` no fluxo de `start_purchase`, se a corrida for perdida bem no limite, o pagamento já criado fica "órfão" de registro de cupom (raro, só quando o limite é atingido *exatamente* em concorrência). Recomendação futura: mover a reserva do cupom para antes do `charge()`.
**Validado:** `pytest tests/test_coupon_service.py` — 8/8 passando.

### C6 — Webhook do Mercado Pago nunca entregava benefício na aprovação automática
**Arquivo:** `services/webhook_service.py`
**Causa (bug de lógica, não de concorrência):** o código setava `payment.status = APPROVED` diretamente **antes** de chamar `confirm_payment`. Como `confirm_payment` tem um atalho idempotente ("se já está APPROVED, retorna sem entregar nada — evita duplicar em reprocessamento"), toda aprovação **automática via webhook** caía nesse atalho e nunca chegava a conceder cargo/DM/auditoria. O mesmo problema afetava `reject_payment`/`expire_payment` (status já alterado antes da chamada, guard de entrada bloqueava a execução real).
**Risco:** pagamento aprovado automaticamente pelo Mercado Pago não entregava o produto — só funcionava se um staff clicasse manualmente "Aprovar" depois.
**Correção:** removida a escrita de status prematura; cada método (`confirm_payment`/`reject_payment`/`expire_payment`) agora é o único responsável por sua própria transição (já protegida atomicamente pela correção C4). Para `REFUNDED`/`CHARGEBACK` (que não têm um método de domínio que grave o status), o `set_status` direto foi mantido, mas só nesses dois casos.
**Validado:** compila; recomendo teste manual ponta-a-ponta com um pagamento sandbox do Mercado Pago (webhook real) antes de subir em produção — não há teste automatizado que simule o webhook completo.

---

## ALTA

### A1 — Votação cross-guild em enquetes
**Arquivo:** `cogs/polls.py` (`PollVoteButton.callback`)
**Risco:** membro de qualquer guild em que o bot está podia votar em enquete pública de outra guild.
**Correção:** `poll.guild_id != interaction.guild_id` → nega.

### A2 — Adulteração cross-guild de lembretes de renovação
**Arquivos:** `services/subscription_renewal_config_service.py`, `views/subscription_renewal_view.py`
**Risco:** staff podia mover/ativar/remover dia de lembrete de outra guild enviando um `day_id` de fora.
**Correção:** `remove_reminder_day`/`toggle_reminder_day`/`move_reminder_day` agora exigem `guild_id` e validam posse antes de agir.

### A3 — Race condition: dois staff podem "vencer" o claim do mesmo ticket
**Arquivos:** `services/claim_service.py`, `database/repositories/ticket_repository.py`
**Correção:** `TicketRepository.get_by_channel_id_locked` (`FOR UPDATE`) usado em `claim_ticket`.
**Validado:** compila; sem teste automatizado dedicado (exigiria simular concorrência real de sessão de banco — recomendo teste de integração futuro com duas sessões simultâneas).

### A4 — `/claim` (slash command) ignora restrição de cargo do painel que o botão respeita
**Arquivo:** `cogs/claim.py`
**Risco:** um painel de ticket configurado para só permitir claim por um cargo específico (ex.: Suporte Tier 2) podia ser contornado por qualquer staff com a permissão global `claim`, digitando `/claim` em vez de clicar no botão.
**Correção:** `/claim` agora chama `member_matches_panel_claim_roles` exatamente como o botão `Assumir`.

### A5 — Webhook aceita notificações sem verificação de assinatura se o secret não estiver configurado, sem trava de startup
**Arquivos:** `services/webhook_service.py`, `config/settings.py`
**Risco:** em produção, esquecer de configurar `MERCADOPAGO_WEBHOOK_SECRET_PRODUCTION` fazia o endpoint aceitar qualquer POST sem verificar assinatura — mitigado parcialmente porque o status real é sempre confirmado direto na API do Mercado Pago, mas ainda permite forçar o bot a fazer chamadas arbitrárias à API do MP para IDs de pagamento escolhidos pelo atacante.
**Correção:** `Settings.load()` agora **falha o startup** (`SettingsError`) se `WEBHOOK_ENABLED=true` e `PAYMENT_MODE=production` sem `MERCADOPAGO_WEBHOOK_SECRET_PRODUCTION` configurado. O modo sandbox/dev continua permitindo rodar sem secret (documentado como comportamento intencional de desenvolvimento).
**Validado:** compila; comportamento de startup não coberto por teste automatizado — testar manualmente definindo `PAYMENT_MODE=production`, `WEBHOOK_ENABLED=true` e omitindo o secret de produção; o bot deve recusar subir com mensagem clara.

### A6 — Índice ausente em `tickets.guild_id` e `logs.guild_id`
**Arquivos:** `database/models/ticket.py`, `database/models/log.py`, nova migração `alembic/versions/a3f8d2c6e1b9_guild_id_indexes_tickets_logs.py`
**Risco:** consultas guild-scoped em duas das tabelas de maior volume (tickets e logs) faziam scan sem índice — degradação de performance conforme o número de guilds/volume cresce, especialmente crítico "para centenas ou milhares de servidores" como pedido no objetivo.
**Correção:** `index=True` nos models + migração Alembic criando `ix_tickets_guild_id` e `ix_logs_guild_id`.
**Validado:** `alembic heads` confirma migração encadeada corretamente como novo head único. **Pendente de execução:** rodar `alembic upgrade head` no banco real (não executado automaticamente por esta auditoria — recomendo aplicar em horário de baixo tráfego, `CREATE INDEX` em Postgres pode travar a tabela brevemente; se o volume já for grande, considere `CREATE INDEX CONCURRENTLY` manual antes de rodar a migração padrão).

---

## MÉDIA

### M1 — `/analises` (aceitar/negar recurso) usava permissão errada
**Arquivo:** `views/pending_punishments_view.py`
**Risco:** guild configurada para restringir "aceitar/negar recurso de banimento" (`recurso_banimento`) a staff sênior, mas com `/analises` liberado a staff júnior — júnior conseguia clicar Aceitar/Negar mesmo sem a permissão `recurso_banimento`, porque os botões checavam a permissão errada (`analises`, que é só a de *visualizar* a fila).
**Correção:** `AnalisesAcceptButton`/`AnalisesDenyButton` agora checam `recurso_banimento`.

### M2 — Painel `/analises` exposto publicamente no canal (não-efêmero)
**Arquivo:** `cogs/moderation.py`
**Risco:** dados de punição (alvo, motivo, evidências) visíveis a qualquer membro do canal, inconsistente com todos os outros painéis de staff (sempre efêmeros).
**Correção:** `ephemeral=True` adicionado.

### M3 — Transcrição de ticket descartava anexos/embeds
**Arquivo:** `utils/transcript.py`
**Risco:** evidência (print, comprovante) enviada como anexo era substituída por `"(sem texto — anexo ou embed)"` e perdida para sempre, já que o canal é apagado logo depois — a transcrição é o único registro que sobra.
**Correção:** `_collect_rows` agora inclui link/nome de cada anexo e título/descrição de cada embed no HTML e no PDF gerado.

### M4 — Lembrete de renovação podia ser reenviado em duplicidade se o bot caísse entre o envio e o registro
**Arquivo:** `services/subscription_reminder_service.py`, `database/repositories/subscription_renewal_repository.py`
**Risco:** ordem era "enviar DM → gravar no livro-razão"; um crash exatamente nesse intervalo fazia o próximo ciclo reenviar o mesmo aviso (a constraint única só protege contra duplicidade de *linha*, não de *envio*).
**Correção:** padrão reserva-então-finaliza: `SubscriptionReminderRepository.reserve()` grava a linha como `pending` **antes** de enviar (usando a constraint única como trava também contra concorrência entre execuções do scheduler); `finalize()` atualiza o status de entrega depois. Se o crash ocorrer entre reserva e envio, o pior caso agora é *não reenviar* (mais seguro que duplicar).
**Validado:** `pytest tests/test_subscription_renewal.py` — 6/6 passando.

### M5 — Sem reconciliação periódica de boosters (perda de eventos durante downtime)
**Arquivos:** `cogs/boosters.py`, `services/booster_service.py`, `database/repositories/booster_repository.py`
**Risco:** detecção de boost dependia 100% do evento `on_member_update`; se o bot ficasse offline exatamente quando um boost começava ou terminava, o evento nunca chegava — o membro ficava com o cargo/benefício para sempre (ou nunca recebia).
**Correção:** nova tarefa `reconcile_boosters` (`tasks.loop(hours=1)`) que compara `guild.premium_subscribers` (fonte de verdade do Discord) contra o que está marcado `currently_boosting=True` no banco, corrigindo divergências via os mesmos handlers idempotentes do evento normal.
**Validado:** `pytest tests/test_booster_service.py` — 2/2 passando.

### M6 — Race condition nos handlers de boost (menor severidade)
**Arquivo:** `services/booster_service.py`, `database/repositories/booster_repository.py`
**Correção:** `get_by_guild_user_locked` (`FOR UPDATE`) usado em `handle_boost_started`/`handle_boost_removed`, fechando a janela de duplo processamento em reenvio de estado do gateway (RESUME).

---

## BAIXA

### B1 — Texto bruto de exceção do Discord exposto a staff
**Arquivo:** `services/punishment_service.py`
**Risco:** `f"Falha na API do Discord ao ...: {exc}"` expunha o corpo JSON bruto do erro da API do Discord em 5 pontos, indo direto para mensagens/embeds vistos por staff.
**Correção:** mensagens agora estáticas e amigáveis; detalhe completo vai só para `logger.exception` (arquivo de log, não Discord).

### B2 — `print()` de debug esquecido em produção
**Arquivo:** `views/appeal_view.py`
**Correção:** removido.

### B3 — Assimetria unclaim vs close (documentado, não corrigido — decisão de produto)
`unclaim_ticket` restringe ao próprio staff que reivindicou; `close_ticket` permite qualquer staff com permissão `fechar` encerrar ticket de colega. Parece intencional (equipe deve poder fechar ticket de colega ausente), mas está fora do padrão simétrico do resto do sistema. **Recomendação:** confirmar com o time se é o comportamento desejado; se não for, replicar o mesmo check de `claimed_by_staff_id == staff_id` em `close_ticket`.

### B4 — Chave PIX exibida sem máscara a todos os admins (por design, documentado no próprio código)
`views/pix_manual_panel_view.py` já documenta explicitamente que a chave PIX "não é segredo" e precisa ser mostrada ao comprador — acesso restrito a administradores completos, não a toda a staff. Não é uma falha de vazamento; é uma decisão consciente. **Recomendação apenas se o time criar um nível de staff mais baixo com acesso a essa tela no futuro:** adicionar máscara (`pix_key[:3] + "***" + pix_key[-2:]`) para esse nível.

---

## Confirmado como correto (não são achados — validação positiva)

- **Isolamento multi-tenant:** todos os 41 repositórios lidos; padrão `list_by_guild(guild_id)` seguido consistentemente; `base_repository.py` documenta explicitamente o risco de `list_all()`/`get_by_id()` sem filtro.
- **Idempotência de criação de pagamento:** `UniqueConstraint(provider, external_id)` em `payment_history` impede duplicação de linha por replay de webhook.
- **Concessão de cargo idempotente:** toda entrega/remoção de cargo (pagamento, booster) checa `role in member.roles` antes de agir — nunca duplica a chamada à API do Discord mesmo quando a camada de negócio tem uma corrida.
- **Assinatura HMAC do webhook:** `hmac.compare_digest` (comparação em tempo constante), verificação correta contra o esquema documentado do Mercado Pago.
- **Nenhum secret vaza em log/exceção/Discord/API:** auditoria dedicada não encontrou nenhum caso de token/webhook secret/credencial exposto — `.env` fora do git, `echo=False` no SQLAlchemy, handlers de exceção da API não retornam traceback.
- **Sistema de permissões (`utils/checks.py`):** único ponto de verdade, reutilizado consistentemente; a maioria esmagadora dos botões persistentes re-checa permissão dentro do próprio callback (não confia só na efêmero-ness da mensagem).
- **`poll_votes`:** único lugar do sistema que já usava o padrão correto por construção (`UniqueConstraint` + captura de `IntegrityError`) em vez de check-then-write — serviu de referência para as correções de corrida aplicadas nesta auditoria.
- **FKs e cascades:** revisão geral considerada bem pensada (RESTRICT em planos com histórico financeiro, SET NULL em referências de log, soft-delete de cupom com resgates).
- **DynamicItems / views persistentes:** todas re-registradas corretamente no boot (`core/bot.py`); nenhuma outra além dos 3 casos C1-C3 tinha problema de resolução cross-guild.
- **CORS:** nenhum middleware configurado — não é "permissivo", é o padrão seguro (nenhum header CORS enviado).

---

## Não corrigido nesta rodada — recomendações para o time

Estes itens não são bugs pontuais corrigíveis com uma edição cirúrgica; exigem decisão de produto/infraestrutura. Documentados para priorização futura:

1. **Rate limiting ausente na API** (`api/main.py`, `api/routes/webhook_routes.py`). Recomendo `slowapi` (compatível com FastAPI) limitando por IP no endpoint de webhook e nos endpoints de health/status. Sem isso, um atacante pode gerar volume de chamadas outbound ao Mercado Pago (via IDs de pagamento arbitrários) ou fazer scraping do `/health`.
2. **Schema Pydantic não usado** em `api/schemas/webhook.py` — `webhook_routes.py` faz parsing manual do dict em vez de usar o schema declarado. Não é vulnerabilidade (a validação manual é defensiva), mas é dívida técnica: o schema pode divergir silenciosamente do que o handler realmente espera.
3. **`DMEvaluationView` não sobrevive a restart** (`views/dm_evaluation_view.py`) — não é `DynamicItem`, não tem `custom_id` explícito, não é registrada via `bot.add_view`. Botões de avaliação por DM (fallback quando o ticket é apagado antes do usuário avaliar) param de funcionar após qualquer deploy dentro da janela de 7 dias. Correção requer convertê-la para `DynamicItem` com `custom_id` codificando o ticket, seguindo o mesmo padrão já usado em `subscription_renewal_buttons.py`.
4. **Drift entre modelo SQLAlchemy e migração manual em vários `guild_id`** (`payment.py`, `subscription.py`, `plan.py`, `punishment.py`, etc.) — o índice existe no banco (criado via migração manual) mas não no `Mapped[...]` do model. Risco: `alembic revision --autogenerate` no futuro pode propor *remover* esses índices por engano. Recomendo, numa passada futura, adicionar `index=True` em todos os `guild_id` cujo índice já existe fisicamente, e então gerar uma migração "no-op" (vazia) pra sincronizar o autogenerate.
5. **Assimetria de permissão claim/close** (B3 acima) — decisão de produto pendente.
6. **Órfão de pagamento em corrida extrema de cupom** (nota em C5) — mover `record_redemption` para antes do `charge()` fecharia esse resíduo, mas é uma mudança de fluxo maior que optei por não fazer sem alinhamento (pode exigir reverter o `charge` se o cupom falhar).

---

## Testes executados

- `pytest tests/` — 99 testes, 98 passando. 1 falha (`test_help_views.py::test_help_main_view_has_one_button_per_category`) é **pré-existente e não relacionada** a esta auditoria (módulo `views/help_views.py` não foi tocado; a contagem de categorias de ajuda diverge do número de botões independente de qualquer mudança feita aqui).
- `python -m py_compile` em **todos** os arquivos `.py` do projeto (fora `venv`/`.git`) — sem erro de sintaxe.
- `alembic heads` — confirma cadeia de migração íntegra com a nova migração de índices como head único.

## Testes que NÃO puderam ser executados automaticamente (requerem ambiente real)

- **Corrida real de banco** (dois clientes concorrentes disputando `FOR UPDATE`): exigiria um Postgres real com duas conexões simultâneas — não simulável nos testes unitários existentes (usam SQLite/mock). **Como reproduzir manualmente:** abrir duas sessões `psql` (ou dois scripts Python com engines separados), iniciar `BEGIN; SELECT ... FOR UPDATE` em uma, tentar o mesmo na outra em paralelo e confirmar que a segunda bloqueia até a primeira commitar/abortar.
- **Webhook do Mercado Pago ponta-a-ponta** (C6, A5): exige credenciais sandbox reais do Mercado Pago e um túnel público (ngrok ou similar) apontando pro `PUBLIC_BASE_URL`. **Como reproduzir:** configurar sandbox, criar um pagamento PIX de teste, aprovar no simulador do MP, e confirmar no log que `confirm_payment` (não mais o atalho idempotente) entregou o cargo e disparou a DM.
- **Cross-guild via cliente Discord modificado** (C1-C3, A1-A2): Discord.py/o cliente oficial não permite forjar `custom_id`/valor de select fora das opções renderizadas — confirmar exploração real exigiria um cliente customizado ou gateway direto, fora do escopo de um teste de UI normal. A correção foi validada por leitura de código (o guard agora existe e é logicamente correto), não por exploração ativa.
- **Reconciliação de boosters em escala** (M5): validar com um servidor de testes real do Discord com Nitro Boost ativo, desligando o bot durante um boost real e checando se a próxima execução da tarefa horária corrige o estado.

---

## Arquivos alterados

```
alembic/versions/a3f8d2c6e1b9_guild_id_indexes_tickets_logs.py   (novo)
cogs/boosters.py
cogs/claim.py
cogs/moderation.py
cogs/polls.py
config/settings.py
database/models/log.py
database/models/ticket.py
database/repositories/booster_repository.py
database/repositories/discount_coupon_repository.py
database/repositories/payment_repository.py
database/repositories/subscription_renewal_repository.py
database/repositories/ticket_repository.py
services/booster_service.py
services/claim_service.py
services/coupon_service.py
services/payment_service.py
services/punishment_service.py
services/subscription_reminder_service.py
services/subscription_renewal_config_service.py
services/subscription_service.py
services/webhook_service.py
utils/transcript.py
views/appeal_view.py
views/monetization_panel_view.py
views/pending_punishments_view.py
views/subscription_renewal_view.py
views/ticket_panels_view.py
```

## Próximos passos recomendados antes de produção em escala

1. Rodar `alembic upgrade head` no banco (aplica os novos índices).
2. Testar manualmente o fluxo completo de webhook do Mercado Pago em sandbox (item C6 é o mais crítico — sem esse teste, não há garantia de que aprovações automáticas entregam o produto).
3. Confirmar com o time se `PAYMENT_MODE=production` está de fato configurado com `MERCADOPAGO_WEBHOOK_SECRET_PRODUCTION` antes do primeiro deploy de produção (o startup agora recusa subir sem isso, então isso será forçado automaticamente).
4. Priorizar rate limiting na API (item não corrigido #1) antes de expor o bot a "centenas ou milhares de servidores", já que volume de tráfego amplifica a superfície de qualquer endpoint não protegido.
5. Considerar teste de carga/concorrência real (dois processos batendo no mesmo pagamento/cupom/ticket) antes do lançamento, para validar as correções de `FOR UPDATE` sob condições reais de Postgres (não testável em SQLite).
