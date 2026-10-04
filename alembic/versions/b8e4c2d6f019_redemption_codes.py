"""Durable redemption codes, reservations and dedicated role ownership."""

from alembic import op

revision = "b8e4c2d6f019"
down_revision = "a6d2e8c4f901"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("\nCREATE TABLE redemption_codes (\n\tcode VARCHAR(8) NOT NULL, \n\treward_type VARCHAR(12) NOT NULL, \n\trole_id BIGINT, \n\trole_duration_seconds INTEGER, \n\ttemporary_role_ack BOOLEAN NOT NULL, \n\tmessage TEXT NOT NULL, \n\tdelivery VARCHAR(12) NOT NULL, \n\tstarts_at TIMESTAMP WITH TIME ZONE, \n\texpires_at TIMESTAMP WITH TIME ZONE, \n\tmax_uses INTEGER, \n\tactive BOOLEAN NOT NULL, \n\tguild_id BIGINT NOT NULL, \n\tid UUID DEFAULT gen_random_uuid() NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_redemption_code_guild UNIQUE (guild_id, code), \n\tCONSTRAINT ck_redemption_code_format CHECK (code ~ '^[A-Z0-9]{8}$' AND code ~ '[A-Z]' AND code ~ '[0-9]'), \n\tCONSTRAINT ck_redemption_max_uses CHECK (max_uses IS NULL OR max_uses > 0), \n\tCONSTRAINT ck_redemption_duration CHECK (role_duration_seconds IS NULL OR role_duration_seconds > 0), \n\tCONSTRAINT ck_redemption_reward CHECK (reward_type IN ('message', 'role')), \n\tCONSTRAINT ck_redemption_delivery CHECK (delivery IN ('channel', 'dm')), \n\tCONSTRAINT ck_redemption_role CHECK ((reward_type = 'role' AND role_id IS NOT NULL) OR (reward_type = 'message' AND role_id IS NULL AND role_duration_seconds IS NULL)), \n\tCONSTRAINT ck_redemption_temporary_ack CHECK (role_duration_seconds IS NULL OR temporary_role_ack), \n\tCONSTRAINT ck_redemption_dates CHECK (starts_at IS NULL OR expires_at IS NULL OR starts_at < expires_at)\n)\n\n")
    op.execute('CREATE INDEX ix_redemption_codes_guild_id ON redemption_codes (guild_id)')
    op.execute('\nCREATE TABLE redemption_role_grants (\n\tuser_id BIGINT NOT NULL, \n\trole_id BIGINT NOT NULL, \n\tstatus VARCHAR(16) NOT NULL, \n\towns_role BOOLEAN NOT NULL, \n\tpermanent BOOLEAN NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE, \n\tgranted_at TIMESTAMP WITH TIME ZONE, \n\torigin_redemption_id UUID, \n\tlease_token UUID, \n\tlease_until TIMESTAMP WITH TIME ZONE, \n\tattempts INTEGER NOT NULL, \n\terror VARCHAR(300), \n\tguild_id BIGINT NOT NULL, \n\tid UUID DEFAULT gen_random_uuid() NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_redemption_member_role UNIQUE (guild_id, user_id, role_id)\n)\n\n')
    op.execute('CREATE INDEX ix_redemption_grant_due ON redemption_role_grants (status, expires_at)')
    op.execute('CREATE INDEX ix_redemption_role_grants_guild_id ON redemption_role_grants (guild_id)')
    op.execute('\nCREATE TABLE redemptions (\n\tcode_id UUID NOT NULL, \n\tuser_id BIGINT NOT NULL, \n\tgrant_id UUID, \n\treward_type VARCHAR(12) NOT NULL, \n\trole_id BIGINT, \n\trole_duration_seconds INTEGER, \n\tmessage TEXT NOT NULL, \n\tdelivery VARCHAR(12) NOT NULL, \n\tstatus VARCHAR(16) NOT NULL, \n\tnotification_status VARCHAR(16) NOT NULL, \n\tattempts INTEGER NOT NULL, \n\tnext_attempt_at TIMESTAMP WITH TIME ZONE, \n\tdelivered_at TIMESTAMP WITH TIME ZONE, \n\trole_expires_at TIMESTAMP WITH TIME ZONE, \n\terror VARCHAR(300), \n\tguild_id BIGINT NOT NULL, \n\tid UUID DEFAULT gen_random_uuid() NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_redemption_code_user UNIQUE (code_id, user_id), \n\tFOREIGN KEY(code_id) REFERENCES redemption_codes (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(grant_id) REFERENCES redemption_role_grants (id) ON DELETE RESTRICT\n)\n\n')
    op.execute('CREATE INDEX ix_redemption_grant_status ON redemptions (grant_id, status)')
    op.execute('CREATE INDEX ix_redemption_pending ON redemptions (status, next_attempt_at)')
    op.execute('CREATE INDEX ix_redemption_notification_due ON redemptions (notification_status, updated_at)')
    op.execute('CREATE INDEX ix_redemptions_code_id ON redemptions (code_id)')
    op.execute('CREATE INDEX ix_redemptions_guild_id ON redemptions (guild_id)')


def downgrade():
    op.drop_table('redemptions')
    op.drop_table('redemption_role_grants')
    op.drop_table('redemption_codes')
