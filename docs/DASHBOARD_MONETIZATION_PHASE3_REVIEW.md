# Dashboard — Fase 3 Monetização: revisão final

Status: implementação concluída para validação local.

## Escopo fechado

### Fase 3.1 — Analytics de monetização

- Resumo financeiro de monetização.
- Métricas de receita aprovada registrada.
- Planos e desempenho.
- Quebra por status de pagamento.
- Pagamentos recentes.
- Leitura de cupons visíveis.
- Usuários por plano/VIP ao clicar no plano.
- Segurança: somente leitura, sem expor QR Code PIX, checkout, dados do pagador ou chaves de gateway.

### Fase 3.2 — Gerenciar planos

- Criar plano.
- Editar plano.
- Ativar/desativar plano.
- Editar nome, descrição, emoji, posição e destaque.
- Editar preços mensal, anual e único.
- Vincular cargo do Discord.
- Atualizar painel fixo da loja quando possível.
- Segurança: usa PlanService, não apaga plano fisicamente e não altera pagamentos, assinaturas, licenças, produtos ou cargos já concedidos.

### Fase 3.3 — Gerenciar cupons

- Criar cupom.
- Editar cupom.
- Ativar/desativar cupom.
- Desconto por porcentagem ou valor fixo.
- Limite global e limite por usuário.
- Data de início e expiração.
- Cargo obrigatório.
- Ciclos permitidos.
- Planos permitidos.
- Segurança: usa CouponService, não deleta cupom pelo painel, não recalcula compras antigas e mantém histórico.
- Auditoria: ações feitas pelo painel aparecem como executor `Painel web`.

### Fase 3.4 — Configurações da loja/pagamento

- Configurar canal da loja.
- Configurar canal de aprovação manual.
- Configurar canal de logs.
- Configurar canal de anúncios de DLC.
- Publicar painel fixo da loja.
- Atualizar painel fixo da loja.
- Mostrar estado do gateway em modo somente leitura.
- Segurança: chaves, tokens, segredo de webhook e modo Mercado Pago continuam no `.env`; o painel não edita nem exibe valores secretos.

## Rotas principais

- `GET /admin/api/guild/{guild_id}/monetization/summary`
- `GET /admin/api/guild/{guild_id}/monetization/plans/{plan_id}/access`
- `GET /admin/api/guild/{guild_id}/monetization/plans/manage`
- `POST /admin/api/guild/{guild_id}/monetization/plans`
- `PATCH /admin/api/guild/{guild_id}/monetization/plans/{plan_id}`
- `POST /admin/api/guild/{guild_id}/monetization/plans/{plan_id}/toggle`
- `GET /admin/api/guild/{guild_id}/monetization/coupons/manage`
- `POST /admin/api/guild/{guild_id}/monetization/coupons`
- `PATCH /admin/api/guild/{guild_id}/monetization/coupons/{coupon_id}`
- `POST /admin/api/guild/{guild_id}/monetization/coupons/{coupon_id}/toggle`
- `GET /admin/api/guild/{guild_id}/monetization/settings`
- `PATCH /admin/api/guild/{guild_id}/monetization/settings`
- `POST /admin/api/guild/{guild_id}/monetization/settings/shop/publish`
- `POST /admin/api/guild/{guild_id}/monetization/settings/shop/refresh`

## Limites intencionais

- O painel não gera cobrança manual nova.
- O painel não aprova pagamento.
- O painel não estorna pagamento.
- O painel não cria assinatura direta.
- O painel não concede licença direta.
- O painel não adiciona/remove cargos de membros diretamente.
- O painel não edita `.env`.
- O painel não mostra token, access token, public key, webhook secret, QR Code PIX ou link de checkout sensível.

## Checklist de validação local

```bat
python -m pytest tests/test_admin_monetization_static.py tests/test_admin_dlc_access_static.py tests/test_admin_monetization_plan_management_static.py tests/test_admin_monetization_coupon_management_static.py tests/test_admin_monetization_settings_static.py tests/test_admin_monetization_phase3_final_static.py tests/test_admin_settings_router_static.py
python -m ruff check api/routes/admin/monetization_plans_router.py api/routes/admin/monetization_coupons_router.py api/routes/admin/monetization_settings_router.py tests/test_admin_monetization_phase3_final_static.py
cd frontend
npm run build
```

## Checklist manual no painel

1. Abrir `Monetização`.
2. Confirmar que Analytics carrega.
3. Criar/editar/desativar/ativar um plano de teste.
4. Criar/editar/desativar/ativar um cupom de teste.
5. Salvar canais da loja/pagamento.
6. Publicar loja.
7. Atualizar loja.
8. Confirmar logs com executor `Painel web`.
9. Confirmar que nenhuma tela mostra QR Code PIX, token, chave ou segredo.

## Resultado esperado

Com os testes e o checklist manual passando, a Fase 3 de monetização fica fechada e a próxima etapa do plano geral pode continuar fora da monetização.
