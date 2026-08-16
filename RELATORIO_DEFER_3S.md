# Relatório: comandos com erro falso de "não respondeu" (timeout 3s do Discord)

## Causa raiz

Discord exige que toda interação (slash command, botão, select, modal) receba uma
resposta inicial — `interaction.response.defer()` ou `interaction.response.send_message()`
— em até 3 segundos. Se isso não acontece, o cliente do Discord mostra
"The application did not respond" / erro na interação, **mesmo que o bot continue
processando e termine o comando com sucesso do lado do servidor**.

No código atual, ~140 handlers (comandos + botões + selects + modais) fazem consulta
no banco (às vezes mais de uma, em sequência) — e em alguns casos até uma chamada
real à API do Discord (ex.: criar canal de voz) — **antes** de chamar `defer()` ou
`send_message()`. Só uns 19 handlers fazem `defer()` como primeira linha, do jeito certo.

Se o banco demorar um pouco (fila de conexão, cold start, lock), estoura os 3s e
aparece o erro — mesmo o comando funcionando.

Bônus: todo comando protegido por checagem de permissão (`has_permission`, `is_staff`,
`member_is_admin`, etc. em `utils/checks.py`) faz uma query de banco *antes* mesmo de
chegar no corpo do handler — isso consome parte do orçamento de 3s até em comandos
que depois fazem `defer()` certinho.

## Fix (não aplicado ainda — só diagnóstico)

Mecânico: mover `await interaction.response.defer()` (ou `defer(ephemeral=True)`
onde já é assim) pra primeira linha de cada handler, antes de qualquer `await` em
serviço/banco/Discord. O resto do código não muda.

## Piores casos (sem defer nenhum, múltiplas queries seguidas)

| Arquivo | Handler | Problema |
|---|---|---|
| `cogs/status.py:17` | `/status` | 2 queries sequenciais (`list_open_by_guild` + `ranking_service.compute`), zero defer |
| `views/ticket_actions_view.py:125` | `create_voice_channel` | 3 queries + `guild.create_voice_channel(...)` (chamada real à API do Discord, pode passar de 3s sozinha) antes de responder |
| `views/coupon_panel_view.py` | quase todos os botões/selects/modais (~840 linhas) | 1-3 queries por handler, nenhum `defer()` no arquivo inteiro |
| `views/monetization_panel_view.py` | idem | mesmo padrão |
| `views/settings_panel.py` | idem | mesmo padrão |
| `views/subscription_renewal_view.py` | idem | mesmo padrão |
| `views/ticket_panels_view.py` | idem | mesmo padrão |
| `views/enquete_panel_view.py` | idem | mesmo padrão |
| `views/payment_dm_panel_view.py` | idem | mesmo padrão |
| `views/audit_log_panel_view.py` | idem | mesmo padrão |
| `views/giveaway_panel_view.py` | idem | mesmo padrão |
| `views/blacklist_action_view.py:65,84,105` | `ban`, `kick`, `blacklist` | checagem (DB) → ação no Discord (ban/kick/timeout) → log (DB) → só responde no fim |

## Slash commands (`cogs/`) — lista completa

| Arquivo:linha | Comando | Veredito |
|---|---|---|
| cogs/audit.py:43 | `audit` | risco — DB antes da resposta |
| cogs/claim.py:20 | `claim` | risco |
| cogs/claim.py:57 | `unclaim` | risco |
| cogs/help.py:19 | `help_command` | risco |
| cogs/logs.py:19 | `logs` | risco |
| cogs/moderation.py:251 | `punir` | risco |
| cogs/moderation.py:540 | `historico` | risco |
| cogs/moderation.py:551 | `punicao_ver` | risco |
| cogs/moderation.py:574 | `recorrer` | risco |
| cogs/moderation.py:605 | `revogar_punicao` | risco |
| cogs/moderation.py:667 | `analises` | risco |
| cogs/painel.py:58 | `painel-setup` | seguro (defer já é a primeira linha) |
| cogs/painel.py:78 | `dashboard-setup` | seguro |
| cogs/ranking.py:28 | `ranking` | risco |
| cogs/shop.py:24 | `loja` | risco (loop N+1 de queries) |
| cogs/shop.py:62 | `monetizacao` | seguro |
| cogs/staff.py:17 | `staff` | risco |
| cogs/status.py:17 | `status` | risco — pior caso |
| cogs/verification.py:61 | `aprovar_verificacao` | seguro |

## Views confirmadas seguras (não mexer)

`views/config_import_view.py`, `views/config_reset_view.py`, `views/confirm_close_view.py`,
`views/comunidade_panel_view.py`, `views/painel_view.py`, `views/partnership_view.py`,
`views/punishment_confirmation_view.py`, `views/punishment_execute_view.py`,
`views/pending_punishments_view.py` (maior parte), `views/ticket_panel_open_view.py`,
`views/verification_view.py` (2 dos 3 handlers).

## Prioridade recomendada pra quando decidir corrigir

1. `cogs/status.py` (`/status`) e `views/ticket_actions_view.py` (`create_voice_channel`) — os
   casos mais graves e prováveis de reproduzir o erro.
2. Os arquivos de painel (`coupon_panel_view.py`, `monetization_panel_view.py`,
   `settings_panel.py`, `subscription_renewal_view.py`, `ticket_panels_view.py`,
   `enquete_panel_view.py`, `payment_dm_panel_view.py`, `audit_log_panel_view.py`,
   `giveaway_panel_view.py`) — mesmo padrão repetido, um fix mecânico resolve todos.
3. Mover/otimizar a checagem de permissão em `utils/checks.py` pra rodar depois do
   `defer()` inicial (ou ser mais rápida), já que ela tributa todo comando protegido.
