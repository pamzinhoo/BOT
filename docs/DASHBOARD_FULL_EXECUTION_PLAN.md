# Dashboard Web 100% — Plano de Execução Completo

Branch de trabalho: `feat/dashboard-phase2-safe`

Objetivo: transformar o painel web em uma interface administrativa real do BOT LIMERENCE, sem campos decorativos, sem duplicar lógica do `/config`, sem ações perigosas sem validação, e mantendo o Discord como fonte operacional viva.

Regra principal:

```text
Discord /config + services existentes + banco real <-> Admin API <-> Web Dashboard
```

Nenhuma página nova deve salvar dados por fora do service correto. Se não existir service seguro para uma ação, primeiro criar o método no service, depois expor na API, depois criar UI.

---

## Estado atual antes das próximas fases

Já feito na branch:

- Settings usam chaves namespaced, por exemplo `avaliacoes.enabled` e `verificacao.enabled`.
- PATCH resolve a chave namespaced para o campo real antes de chamar o updater existente.
- Bug de boolean corrigido: `False` não vira string `"False"`.
- Validação de canal/cargo contra o Discord antes de salvar.
- Aviso visual quando canal/cargo salvo não existe mais.
- Campos de tempo com unidade clara.
- Endpoint SSE `/admin/api/events` para invalidação do dashboard.
- Sidebar não mostra página falsa de Sorteios/DLCs.

---

# Fase 1 — Sorteios reais no painel

## Meta

Criar página real `/admin/giveaways` para gerenciar sorteios usando `GiveawayService`, sem duplicar lógica do Discord.

## Backend

Criar router separado:

```text
api/routes/admin/giveaways_router.py
```

Registrar em:

```text
api/routes/admin/__init__.py
```

Endpoints planejados:

```text
GET    /admin/api/guild/{guild_id}/giveaways
POST   /admin/api/guild/{guild_id}/giveaways
POST   /admin/api/guild/{guild_id}/giveaways/{giveaway_id}/close
POST   /admin/api/guild/{guild_id}/giveaways/{giveaway_id}/reroll
POST   /admin/api/guild/{guild_id}/giveaways/{giveaway_id}/cancel
GET    /admin/api/guild/{guild_id}/giveaways/{giveaway_id}/participants
```

## Regras obrigatórias

- Validar guild.
- Validar canal de texto.
- Validar cargo permitido, se informado.
- Validar cargo de prêmio, se prêmio for cargo.
- Validar duração maior que zero.
- Validar quantidade de vencedores maior que zero.
- Criar sorteio usando service existente.
- Publicar mensagem real no Discord.
- Registrar audit log.
- Enviar evento SSE/invalidação depois de criar/encerrar/cancelar/rerollar.
- Cancelar deve ser implementado no service, não com SQL solto na rota.

## Frontend

Criar:

```text
frontend/src/pages/GiveawaysPage.tsx
```

Atualizar:

```text
frontend/src/App.tsx
frontend/src/components/AppShell.tsx
frontend/src/lib/api.ts
```

UI necessária:

- Tabela/cards de sorteios ativos e finalizados.
- Botão `Criar sorteio`.
- Formulário com canal, título, descrição, duração, vencedores, tipo de prêmio.
- Ações com confirmação: encerrar, cancelar, rerollar.
- Estado vazio quando não houver sorteio.
- Erros claros quando o bot não tem permissão no canal.

## Testes

- API bloqueia canal inexistente.
- API bloqueia duração inválida.
- API usa `GiveawayService`.
- UI builda.

---

# Fase 2 — DLCs reais no painel

## Meta

Criar página `/admin/dlcs` para gerenciar DLCs usando `DlcService`.

## Backend

Criar router:

```text
api/routes/admin/dlcs_router.py
```

Endpoints:

```text
GET    /admin/api/guild/{guild_id}/dlcs
POST   /admin/api/guild/{guild_id}/dlcs/free
POST   /admin/api/guild/{guild_id}/dlcs/paid
PATCH  /admin/api/guild/{guild_id}/dlcs/{product_id}
POST   /admin/api/guild/{guild_id}/dlcs/{product_id}/toggle
POST   /admin/api/guild/{guild_id}/dlcs/{product_id}/disable
```

## Regras obrigatórias

- DLC gratuita deve usar o cargo `verificado` configurado no bot.
- DLC paga exige cargo exclusivo e preço válido.
- Não inventar integração com launcher/R2/itch nessa fase.
- Editar preço deve chamar `DlcService.update_price`.
- Editar cargo deve chamar `DlcService.update_role`.
- Ativar/desativar deve chamar `DlcService.toggle_active` ou `disable`.
- Registrar audit log pelo service.
- Atualizar loja/painel quando o service já fizer isso.

## Frontend

Criar:

```text
frontend/src/pages/DlcsPage.tsx
```

UI necessária:

- Listar DLCs grátis/pagas.
- Mostrar status ativa/inativa.
- Criar DLC gratuita.
- Criar DLC paga com preço/cargo.
- Editar nome/descrição/preço/cargo/status.
- Aviso se cargo verificado não estiver configurado.

## Testes

- Criar grátis sem cargo verificado deve falhar com erro claro.
- Criar paga sem cargo deve falhar.
- Preço inválido deve falhar.
- Não deve criar Product/Plan duplicado com slug repetido.

---

# Fase 3 — Monetização, planos, produtos, cupons e pagamentos

## Meta

Criar administração web para monetização sem quebrar fluxo Mercado Pago/pagamento já existente.

## Backend

Criar router:

```text
api/routes/admin/monetization_router.py
```

Endpoints planejados:

```text
GET    /admin/api/guild/{guild_id}/monetization/summary
GET    /admin/api/guild/{guild_id}/plans
POST   /admin/api/guild/{guild_id}/plans
PATCH  /admin/api/guild/{guild_id}/plans/{plan_id}
POST   /admin/api/guild/{guild_id}/plans/{plan_id}/toggle
GET    /admin/api/guild/{guild_id}/coupons
POST   /admin/api/guild/{guild_id}/coupons
PATCH  /admin/api/guild/{guild_id}/coupons/{coupon_id}
GET    /admin/api/guild/{guild_id}/payments
```

## Regras obrigatórias

- Não mexer direto em pagamento se já existir service.
- Não recalcular preço fora do service.
- Não salvar cupom inválido.
- Não permitir preço negativo.
- Não permitir plano ativo sem cargo quando cargo for obrigatório.
- Pagamentos devem ser leitura inicialmente; nada de editar pagamento manualmente.

## Frontend

Criar:

```text
frontend/src/pages/MonetizationPage.tsx
frontend/src/pages/PlansPage.tsx
frontend/src/pages/CouponsPage.tsx
frontend/src/pages/PaymentsPage.tsx
```

UI necessária:

- Resumo de monetização.
- Lista de planos.
- Criar/editar plano.
- Lista de cupons.
- Criar/editar cupom.
- Lista de pagamentos/status.
- Aviso quando gateway não estiver configurado.

---

# Fase 4 — Painéis do Discord

## Meta

O dashboard deve permitir republicar/atualizar painéis reais do Discord.

## Páginas e ações

Adicionar na página de painéis:

- Painel de tickets.
- Painel de verificação.
- Painel de DLCs/loja.
- Painel de ranking/status.

## Regras obrigatórias

- Mostrar se canal existe.
- Mostrar se mensagem salva existe quando possível.
- Botão `Republicar` deve chamar service/view existente.
- Botão `Atualizar` deve reeditar mensagem existente quando o service suportar.
- Se não existir service seguro, criar service antes.
- Nada de simular sucesso.

---

# Fase 5 — Tickets e Staff com ações reais

## Meta

Transformar páginas de ticket/staff de leitura em páginas operacionais.

## Tickets

Ações planejadas:

```text
Assumir
Liberar
Fechar
Reabrir
Excluir
Ver transcrição
Ver avaliação
```

Regras:

- Chamar `TicketService`/views existentes.
- Validar status atual antes da ação.
- Ação destrutiva exige confirmação.
- Auditar tudo.
- Não fechar ticket já fechado.
- Não excluir sem confirmação.

## Staff

Ações planejadas:

```text
Listar staff
Ver métricas
Publicar ranking
Gerenciar cargos/permissões ligados a staff
```

Regras:

- Não editar staff por SQL solto.
- Não conceder cargo acima do bot.
- Não duplicar permissões fora do service.

---

# Fase 6 — Moderação e recursos

## Meta

Criar área real de moderação com recursos/appeals.

## Ações planejadas

```text
Ver punições
Ver recurso pendente
Aprovar recurso
Negar recurso
Ver logs de moderação
```

## Regras obrigatórias

- Validar permissão/hierarquia antes de agir.
- Não banir/kickar pelo painel sem confirmação forte.
- Registrar audit log.
- Mostrar erro do Discord claramente.
- Não permitir ação se bot não tiver permissão.

---

# Fase 7 — Segurança final do painel

## Meta

Evitar que o painel local vire uma porta perigosa quando tiver ações destrutivas.

## Itens obrigatórios

- Rate limit por rota sensível.
- Confirmação para ação destrutiva.
- CSRF/token local para escrita.
- Logs de auditoria com origem `Dashboard local`.
- Separar ação somente leitura de ação de escrita.
- Nunca expor token/secret no frontend.
- Validar guild em toda rota.
- Validar canal/cargo em toda rota.
- Bloquear ação se o bot não estiver pronto.

---

# Fase 8 — Testes e checklist final

## Backend

Rodar:

```bash
python -m pytest
python -m ruff check .
```

Quando o ruff completo tiver erros antigos fora do escopo, rodar pelo menos:

```bash
python -m ruff check api/routes/admin services views tests
```

## Frontend

Rodar:

```bash
cd frontend
npm run build
```

## Teste manual real

1. Abrir dashboard local.
2. Verificar se servidor aparece certo.
3. Mudar verificação para off e salvar.
4. Conferir no Discord se `/config` reflete o mesmo valor.
5. Ligar de novo e conferir.
6. Mudar avaliações off/on.
7. Trocar canal de log para canal real.
8. Tentar salvar canal/cargo inválido e confirmar bloqueio.
9. Criar sorteio real pelo painel.
10. Encerrar sorteio pelo painel.
11. Rerollar sorteio pelo painel.
12. Criar DLC grátis.
13. Criar DLC paga.
14. Editar preço/cargo da DLC paga.
15. Conferir auditoria.
16. Reiniciar bot e confirmar que painel não perde estado.
17. Alterar uma config pelo Discord `/config` e confirmar atualização no web dashboard sem F5.

---

# Ordem de implementação segura

1. Sorteios.
2. DLCs.
3. Painéis do Discord.
4. Tickets/Staff actions.
5. Monetização.
6. Moderação/recursos.
7. Segurança final.
8. Testes completos.

Motivo: Sorteios e DLCs são prioridade visual/operacional. Monetização e moderação ficam depois porque têm maior risco de impacto financeiro ou punição errada.
