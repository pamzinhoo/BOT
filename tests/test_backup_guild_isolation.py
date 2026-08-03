from __future__ import annotations

from pathlib import Path

from cogs.backup import BackupCog, _guild_scoped_queries
from database.models.achievement import Achievement
from database.models.claim import Claim
from database.models.evaluation import Evaluation
from database.models.guild_settings import GuildSettings
from database.models.log import LogEntry
from database.models.staff import Staff
from database.models.staff_stats import StaffStats
from database.models.ticket import Ticket
from database.models.ticket_message import TicketMessage

_ALL_DUMPED_MODELS = [
    Achievement, Claim, Evaluation, GuildSettings, LogEntry, Staff, StaffStats, Ticket, TicketMessage,
]


def test_every_dumped_table_query_is_filtered_by_guild() -> None:
    """Auditoria (critico): a versao anterior dumpava cada tabela SEM filtro
    de guild — um unico zip com o backup de TODAS as guilds era enviado pro
    canal de backup de CADA servidor. Toda query de dump agora tem que
    restringir por guild_id (direto ou via join ate uma tabela que tenha)."""
    queries = _guild_scoped_queries(guild_id=123456)
    assert set(queries.keys()) == set(_ALL_DUMPED_MODELS)
    for model, query in queries.items():
        compiled = str(query)
        assert "guild_id" in compiled, f"query de {model.__name__} nao filtra por guild_id: {compiled}"
        assert "WHERE" in compiled.upper(), f"query de {model.__name__} nao tem WHERE algum: {compiled}"


def test_copy_transcripts_only_copies_files_for_this_guild_tickets(tmp_path: Path) -> None:
    """Auditoria (critico): `data/transcripts` e uma pasta compartilhada entre
    TODAS as guilds (nomeada pelo UUID completo do ticket, nao mais so os 8
    primeiros chars — um prefixo curto tinha risco real de colisao entre
    tickets de guilds diferentes) — copiar a pasta inteira pro backup de uma
    guild vazaria as transcricoes de tickets de outros servidores. So os
    arquivos cujo UUID pertence a esta guild podem ser copiados."""
    ticket_a = "aaaaaaaa-0000-0000-0000-000000000001"
    ticket_b = "bbbbbbbb-0000-0000-0000-000000000002"
    transcripts_dir = tmp_path / "transcripts"
    transcripts_dir.mkdir()
    (transcripts_dir / f"{ticket_a}.html").write_text("guild A ticket")
    (transcripts_dir / f"{ticket_a}.pdf").write_bytes(b"guild A ticket pdf")
    (transcripts_dir / f"{ticket_b}.html").write_text("guild B ticket - NAO pode vazar")
    (transcripts_dir / f"{ticket_b}.pdf").write_bytes(b"guild B ticket pdf - NAO pode vazar")

    out_dir = tmp_path / "backup-guild-a" / "transcricoes"

    import cogs.backup as backup_module

    original_dir = backup_module.TRANSCRIPTS_DIR
    backup_module.TRANSCRIPTS_DIR = transcripts_dir
    try:
        BackupCog._copy_transcripts(out_dir, {ticket_a})
    finally:
        backup_module.TRANSCRIPTS_DIR = original_dir

    copied = {p.name for p in out_dir.iterdir()}
    assert copied == {f"{ticket_a}.html", f"{ticket_a}.pdf"}
    assert f"{ticket_b}.html" not in copied
    assert f"{ticket_b}.pdf" not in copied


def test_run_generates_one_backup_per_guild_not_a_shared_zip() -> None:
    """Confere que o fluxo principal (`_run`) itera guild por guild chamando
    `_backup_guild` (1 stage dir / 1 zip por guild) em vez de montar um unico
    zip global e distribuir pra todo mundo — a regressao especifica que foi
    corrigida nesta auditoria."""
    import inspect

    source = inspect.getsource(BackupCog._run)
    assert "_backup_guild" in source, (
        "_run precisa delegar pra _backup_guild (1 zip por guild) — "
        "monte um zip compartilhado de novo seria reintroduzir o vazamento cross-guild"
    )
