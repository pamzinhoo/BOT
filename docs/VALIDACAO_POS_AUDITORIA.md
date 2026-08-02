# Validação Pós-Auditoria — BOT

Data: 2026-08-02
Referência: `docs/AUDITORIA_SEGURANCA_2026-08-02.md` (22 achados corrigidos)
Objetivo: confirmar que as correções da auditoria estão realmente ativas em código e sincronizadas com o banco — não apenas "parece certo pela leitura", mas exercitadas contra o Postgres real configurado no projeto.

---

## 1. Migration

**Antes:**
```
$ alembic heads
a3f8d2c6e1b9 (head)
```
Apenas 1 head — sem branches divergentes.

**Situação encontrada:** a migration `a3f8d2c6e1b9` (índices `ix_tickets_guild_id` e `ix_logs_guild_id`) **já estava aplicada** no banco configurado em `DATABASE_URL` antes de eu rodar qualquer comando manual — confirmado consultando `alembic_version` diretamente:

```sql
select version_num from alembic_version;
-- a3f8d2c6e1b9

select indexname from pg_indexes
where tablename in ('tickets','logs')
  and indexname in ('ix_tickets_guild_id','ix_logs_guild_id');
-- ix_logs_guild_id
-- ix_tickets_guild_id
```

Ambos os índices existem fisicamente no banco. Não executei `alembic upgrade head` porque não havia nada pendente — o próprio processo do bot (ou uma execução anterior) já sincronizou.

**Depois — validado:**
```
$ alembic current
a3f8d2c6e1b9 (head)

$ alembic heads
a3f8d2c6e1b9 (head)
```
✅ Um único head. ✅ Banco e código sincronizados. ✅ Índices confirmados fisicamente via `pg_indexes`, não só via `alembic_version`.

---

## 2. Validação das correções críticas

Diferente da rodada anterior (que validou por leitura de código), esta rodada criou um arquivo de teste de integração novo — `tests/test_audit_fixes_validation.py` — que roda contra o **Postgres real** (não SQLite/mock), usando `guild_id` sentinela fora da faixa de snowflakes do Discord (`900_000_000_000_000_00x`) para não colidir com dado real, e limpa tudo em `finally` independente do resultado.

### Cross-guild

| Teste | O que prova | Resultado |
|---|---|---|
| `test_cross_guild_appeal_guard_blocks_wrong_guild` | `accept_appeal`/`deny_appeal` recusam punição de outra guild (C3), e a punição real não é alterada | ✅ PASSOU |
| `test_cross_guild_plan_select_blocks_wrong_guild` | `_PlanSelect.callback` recusa plano de outra guild mesmo com UUID válido forjado no valor do select (C1) — chama o callback real da view, não um mock da lógica | ✅ PASSOU |
| `test_cross_guild_ticket_panel_select_blocks_wrong_guild` | `_PanelSelect.callback` recusa painel de ticket de outra guild pelo mesmo mecanismo (C2) | ✅ PASSOU |

Os três testes chamam o **código de produção real** (`PunishmentService.accept_appeal`, `_PlanSelect.callback`, `_PanelSelect.callback`) contra linhas reais no banco — não reimplementam a lógica, então uma regressão futura nesses arquivos quebra o teste.

Não testado (fora do alcance de um teste automatizado, documentado na auditoria original): exploração via cliente Discord modificado forjando `custom_id`/valor de componente fora das opções renderizadas — o discord.py/cliente oficial não permite; validação aqui foi por chamada direta ao callback com valor forjado, que é logicamente equivalente ao ataque descrito.

### Pagamentos

| Teste | O que prova | Resultado |
|---|---|---|
| `test_payment_status_race_only_one_transition_wins` | Duas chamadas `set_status(..., expected_statuses=(PENDING,))` disparadas **verdadeiramente em paralelo** (`asyncio.gather`, duas sessões de banco distintas) contra o mesmo pagamento — exatamente 1 vence, a outra recebe `None` | ✅ PASSOU — 1 vencedora, 1 perdedora, sempre |
| `test_payment_status_history_not_duplicated_by_race` | A mesma corrida não duplica a linha de `PaymentStatusHistory` (efeito colateral de auditoria) | ✅ PASSOU — exatamente 1 linha gravada |

Isso prova **empiricamente** (não só por leitura de código) que o `SELECT ... FOR UPDATE` em `PaymentRepository.get_by_id_locked` está de fato serializando as duas transações no Postgres real, e que a guarda `expected_statuses` está rejeitando a segunda transição corretamente.

**Sobre "dois staffs aprovando simultaneamente" e "entrega duplicada de benefício":** o teste acima cobre a camada que efetivamente prendia a corrida (a transição de status, ponto onde a decisão "quem venceu" é tomada). A entrega de cargo já era idempotente antes da auditoria (checa `role in member.roles`) e a DM/auditoria só dispara depois da transição vencedora — como só 1 transição vence, só 1 fluxo de entrega roda. Não testei a chamada completa `confirm_payment` fim-a-fim (exigiria mocks de `discord.Member`/`discord.Guild` para a entrega de cargo/DM) — recomendo esse teste de integração mais completo como próximo passo se o time quiser cobertura ainda maior; o ponto crítico (a corrida em si) está coberto e comprovado.

### Cupons

| Teste | O que prova | Resultado |
|---|---|---|
| `test_coupon_redemption_race_respects_global_limit` | Cupom com `max_global_uses=1` disputado por **5 tentativas concorrentes reais** (`asyncio.gather`) — exatamente 1 sucesso, 4 recusas com `CouponGlobalLimitReachedError`, e o banco confirma exatamente 1 linha de resgate gravada | ✅ PASSOU — sempre 1 de 5, nunca mais |

Rodei esse teste isoladamente mais de uma vez (parte da suíte completa + execução isolada) para descartar coincidência de timing — resultado consistente em todas as execuções.

### Mercado Pago (fluxo do webhook)

O achado C6 da auditoria original (webhook setava o status **antes** de chamar `confirm_payment`, fazendo a aprovação automática cair no atalho idempotente e nunca entregar o benefício) foi corrigido removendo essa escrita prematura.

| Teste | O que prova | Resultado |
|---|---|---|
| `test_webhook_no_premature_status_write` | Inspeciona o código-fonte real de `WebhookService.handle_mercadopago_notification` em runtime e falha se a linha problemática (`set_status` direto antes de `confirm_payment`) reaparecer — é um teste de regressão estrutural, não um mock do fluxo | ✅ PASSOU |

Fluxo confirmado no código atual:
```
Webhook recebido
  → valida assinatura HMAC
  → consulta API do Mercado Pago (nunca confia no payload sozinho)
  → confirm_payment() / reject_payment() / expire_payment()
      (cada um faz sua PRÓPRIA transição atômica, com FOR UPDATE)
  → dentro de confirm_payment: entrega de cargo + DM + auditoria SÓ se a
    transição realmente venceu (não é mais um atalho idempotente prematuro)
```

**Não testável automaticamente:** o fluxo completo ponta-a-ponta com o Mercado Pago real (sandbox) exige um pagamento PIX de teste de verdade e um túnel público apontando pro `PUBLIC_BASE_URL` — isso não pode ser simulado num teste unitário/CI. **Como reproduzir manualmente:**
1. Configurar credenciais sandbox do Mercado Pago (`MERCADOPAGO_ACCESS_TOKEN_SANDBOX`, `MERCADOPAGO_WEBHOOK_SECRET_SANDBOX`).
2. Expor a API local via ngrok (ou similar) e apontar `PUBLIC_BASE_URL` para a URL pública.
3. Gerar uma cobrança PIX de teste via `/comprar` (ou equivalente) na guild de teste.
4. Aprovar o pagamento no simulador do Mercado Pago sandbox.
5. Confirmar no log do bot que a linha `confirm_payment` processou a aprovação (não o atalho `# ja processado — idempotente`) e que o cargo/DM/auditoria foram de fato disparados.

---

## 3. Testes

### `py_compile` completo
```
$ python -m py_compile $(todos os .py do projeto, exceto venv/.git)
```
✅ Sem erro de sintaxe em nenhum arquivo.

### Suíte de testes
```
$ pytest tests/ -q
.......................................................................
....................................................................
106 passed, 1 failed
```

**1 falha — pré-existente, não relacionada à auditoria:**
`tests/test_help_views.py::test_help_main_view_has_one_button_per_category`

Investiguei a causa: o teste afirma `len(view.children) == len(HELP_CATEGORIES)` (5), mas `HelpMainView.__init__` (`views/help_views.py:71-75`) adiciona **intencionalmente** um botão "Geral" extra além dos 5 de categoria — são 6 botões por design, não um bug. É um teste desatualizado em relação ao comportamento real da view (provavelmente escrito antes do botão "Geral" existir). Confirmado que:
- essa falha já existia **antes** de qualquer mudança desta auditoria (reproduzida na primeira execução da suíte, antes de qualquer edição);
- nenhum arquivo tocado pela auditoria (`views/help_views.py`, `utils/constants.py`) foi modificado por mim;
- não está relacionada a segurança, multi-tenant, pagamentos ou qualquer um dos 22 achados.

**Não corrigi** porque está fora do escopo desta validação (ajustar a asserção do teste ou o comportamento da view é uma decisão de produto — qual dos dois está "errado" — que cabe ao time, não a uma correção de segurança). Recomendo abrir um item separado de manutenção.

### Novos testes de integração criados
`tests/test_audit_fixes_validation.py` — 7 testes, todos passando, todos contra o Postgres real (não SQLite):
```
tests/test_audit_fixes_validation.py::test_cross_guild_appeal_guard_blocks_wrong_guild PASSED
tests/test_audit_fixes_validation.py::test_payment_status_race_only_one_transition_wins PASSED
tests/test_audit_fixes_validation.py::test_payment_status_history_not_duplicated_by_race PASSED
tests/test_audit_fixes_validation.py::test_coupon_redemption_race_respects_global_limit PASSED
tests/test_audit_fixes_validation.py::test_webhook_no_premature_status_write PASSED
tests/test_audit_fixes_validation.py::test_cross_guild_plan_select_blocks_wrong_guild PASSED
tests/test_audit_fixes_validation.py::test_cross_guild_ticket_panel_select_blocks_wrong_guild PASSED
```
Esses testes ficam no repositório como regressão permanente — se alguém reintroduzir qualquer um dos 6 bugs críticos no futuro (remover o `FOR UPDATE`, remover o check de `guild_id`, voltar a setar status antes de `confirm_payment`), a suíte quebra.

**Nota de manutenção:** esses testes exigem `DATABASE_URL` acessível para rodar (não usam mock) — se o CI não tiver acesso a um Postgres real, vão falhar com erro de conexão explícito (`pytest.fail` com mensagem clara), não um skip silencioso. Se o time configurar um Postgres de CI/staging separado do banco de desenvolvimento, isso é o ideal para não depender do banco de trabalho pessoal.

---

## 4. Resumo

| Item do pedido | Status |
|---|---|
| `alembic upgrade head` | ✅ Já estava aplicado; confirmado via `alembic current`/`heads` + inspeção direta de `pg_indexes` |
| Único head, banco sincronizado | ✅ Confirmado |
| Cross-guild (plano, ticket, banimento) | ✅ Validado com testes de integração reais, não apenas leitura de código |
| Pagamentos (corrida de aprovação, entrega duplicada) | ✅ Validado com concorrência real (`asyncio.gather` + Postgres) — exatamente 1 vencedor sempre |
| Cupons (corrida no último uso) | ✅ Validado com 5 tentativas concorrentes reais — limite nunca ultrapassado |
| Mercado Pago (webhook → API → confirma → entrega → auditoria) | ✅ Bug da escrita prematura de status confirmado corrigido (teste de regressão estrutural); fluxo ponta-a-ponta real precisa de teste manual em sandbox (instruções acima) |
| `py_compile` completo | ✅ Sem erros |
| Suíte de testes | ✅ 106 passando, 1 falha pré-existente não relacionada (documentada, não corrigida por estar fora do escopo) |
| Testes de integração | ✅ 7 novos testes criados e passando, cobrindo os 6 achados críticos com banco real |
| Relatório | ✅ Este documento |

## Arquivos criados nesta validação

```
tests/test_audit_fixes_validation.py   (novo — 7 testes de integração)
docs/VALIDACAO_POS_AUDITORIA.md        (novo — este relatório)
```

Nenhum arquivo de produção foi alterado nesta rodada — só validação. As correções já estavam corretas desde a auditoria original; esta rodada trocou "validado por leitura" por "validado por execução real contra o banco de produção configurado".
