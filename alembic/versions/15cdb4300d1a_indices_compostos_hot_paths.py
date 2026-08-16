"""indices compostos para hot paths de tickets/punishments/subscriptions/
payment_history/verification_sessions/partnerships

Revision ID: 15cdb4300d1a
Revises: 7d3a9e1c4f68
Create Date: 2026-08-11 12:00:00.000000

Auditoria de performance (Fase 3, docs/AUDITORIA_PERFORMANCE.md): a migration
9f1c7d2a5b4e ja cobriu indices single-column em guild_id nas tabelas mais
volumosas. Essa migration vai um passo alem — indices compostos/parciais
desenhados a partir do padrao REAL das queries (nao de "toda coluna que
aparece em WHERE"), confirmados um a um por leitura dos repositories e por
grep de quem realmente chama cada metodo (varias queries que a auditoria
original tinha marcado como "quentes" acabaram sendo codigo morto sem
nenhum chamador — nao ganharam indice aqui, ver relatorio).

Os labels de enum usados nos predicados parciais (ex.: 'PENDING_REVIEW',
'ACTIVE', 'OPEN') foram confirmados direto no catalogo do Postgres
(pg_enum) antes de escrever esta migration — SQLAlchemy Enum grava o NAME
do membro Python, nao o .value.

CONCURRENTLY nao foi usado: alembic/env.py roda cada migration dentro de
uma transacao (context.begin_transaction()), e CREATE INDEX CONCURRENTLY
nao pode rodar dentro de bloco transacional no Postgres. Como as tabelas
alvo hoje tem poucas dezenas de linhas (ambiente atual), o lock breve de um
CREATE INDEX normal e desprezivel. Se essas tabelas crescerem
significativamente antes do proximo review, considerar
op.get_context().autocommit_block() + CONCURRENTLY numa migration futura.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '15cdb4300d1a'
down_revision: Union[str, None] = '7d3a9e1c4f68'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # punishments: list_by_user / has_revoked_punishment / has_open_punishment_of_type
    # (punishment_service.py) sempre filtram guild_id+user_id; list_by_user
    # tambem ordena por created_at desc com LIMIT 50 — o 3o campo evita um
    # Sort separado apos o index scan.
    op.create_index(
        'ix_punishments_guild_user_created',
        'punishments',
        ['guild_id', 'user_id', sa.text('created_at DESC')],
        unique=False,
    )
    # ReviewExpirationTask (cogs/moderation.py, roda a cada 1 min) varre TODAS
    # as guilds de uma vez atras de punicoes PENDING_REVIEW vencidas — sem
    # filtro de guild_id, entao um indice parcial (so a fatia PENDING_REVIEW,
    # que e pequena e transitoria) e mais direto que um composto com guild_id.
    op.create_index(
        'ix_punishments_pending_review_deadline',
        'punishments',
        ['review_deadline_at'],
        unique=False,
        postgresql_where=sa.text("status = 'PENDING_REVIEW'"),
    )

    # subscriptions: list_active_by_user / list_active_or_pending_by_user /
    # list_active_with_period (usada pelo scheduler de renovacao a cada 15
    # min, uma vez por guild) filtram guild_id+status. guild_id+user_id+
    # plan_id ja tem indice unico (uq_subscription_guild_user_plan) que cobre
    # bem os lookups por usuario; este aqui cobre o eixo status, que aquele
    # nao tem.
    op.create_index(
        'ix_subscriptions_guild_status',
        'subscriptions',
        ['guild_id', 'status'],
        unique=False,
    )

    # payment_history: list_by_user (historico de pagamentos do usuario) —
    # mesma logica do punishments acima.
    op.create_index(
        'ix_payment_history_guild_user_created',
        'payment_history',
        ['guild_id', 'user_id', sa.text('created_at DESC')],
        unique=False,
    )
    # check_expired_payments (cogs/payment_expiration.py, a cada 5 min) varre
    # todos os pagamentos PENDING vencidos, sem filtro de guild — mesmo
    # raciocinio do indice parcial de punishments acima.
    op.create_index(
        'ix_payment_history_pending_expires',
        'payment_history',
        ['expires_at'],
        unique=False,
        postgresql_where=sa.text("status = 'PENDING'"),
    )

    # tickets: count_open_by_member (checagem de limite ao abrir ticket — hot
    # path de verdade, roda em toda tentativa de abertura) + list_open_by_guild
    # + list_awaiting_first_response (ambas rodam em tasks periodicas a cada
    # 1-5 min) compartilham o mesmo filtro guild_id+status IN (OPEN,CLAIMED).
    # Indice parcial: tickets fechados/cancelados (a maioria, com o tempo)
    # nunca entram nele.
    op.create_index(
        'ix_tickets_open_by_guild_member',
        'tickets',
        ['guild_id', 'opened_by_discord_id'],
        unique=False,
        postgresql_where=sa.text("status IN ('OPEN', 'CLAIMED')"),
    )
    # list_by_staff (perfil de staff) ordena por created_at desc;
    # most_common_category_for_staff agrupa sobre o mesmo filtro
    # claimed_by_staff_id — ambas em services/staff_service.py.
    op.create_index(
        'ix_tickets_staff_created',
        'tickets',
        ['claimed_by_staff_id', sa.text('created_at DESC')],
        unique=False,
    )

    # verification_sessions: sweep_expired_verifications (cogs/verification.py,
    # a cada 1 min) varre TODAS as guilds atras de sessoes PENDING vencidas,
    # sem filtro de guild_id — mesmo padrao dos outros sweeps globais acima.
    op.create_index(
        'ix_verification_sessions_pending_expires',
        'verification_sessions',
        ['expires_at'],
        unique=False,
        postgresql_where=sa.text("status = 'PENDING'"),
    )

    # partnerships: get_next_to_announce (base do rodizio de divulgacao
    # automatica, cogs/partnership.py announcement_tick roda a cada 1 min
    # para todas as guilds) filtra guild_id+archived_at IS NULL e ordena por
    # last_announced_at asc nulls first — o indice cobre filtro E ordenacao.
    # list_active_by_guild usa o mesmo filtro (sem a ordenacao).
    op.create_index(
        'ix_partnerships_guild_announce',
        'partnerships',
        ['guild_id', 'last_announced_at'],
        unique=False,
        postgresql_where=sa.text('archived_at IS NULL'),
    )


def downgrade() -> None:
    op.drop_index('ix_partnerships_guild_announce', table_name='partnerships')
    op.drop_index('ix_verification_sessions_pending_expires', table_name='verification_sessions')
    op.drop_index('ix_tickets_staff_created', table_name='tickets')
    op.drop_index('ix_tickets_open_by_guild_member', table_name='tickets')
    op.drop_index('ix_payment_history_pending_expires', table_name='payment_history')
    op.drop_index('ix_payment_history_guild_user_created', table_name='payment_history')
    op.drop_index('ix_subscriptions_guild_status', table_name='subscriptions')
    op.drop_index('ix_punishments_pending_review_deadline', table_name='punishments')
    op.drop_index('ix_punishments_guild_user_created', table_name='punishments')
