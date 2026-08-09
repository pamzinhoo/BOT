from __future__ import annotations

import inspect

from cogs.backup import BackupCog
from services.painel_service import PainelService
from utils.transcript import build_transcript_pdf


def test_dashboard_chart_render_does_not_block_event_loop() -> None:
    """Incidente reportado em producao: com 2 usuarios simultaneos (um usando
    o painel, outro tentando se verificar), o bot inteiro parou de responder.
    Causa raiz: render_ranking_chart (matplotlib, sincrono/CPU-bound) era
    chamado direto dentro do handler assincrono, travando o UNICO event loop
    do bot pra todas as guilds enquanto o grafico renderizava. Precisa rodar
    numa thread separada via asyncio.to_thread."""
    source = inspect.getsource(PainelService._refresh_dashboard_message)
    assert "asyncio.to_thread" in source, (
        "render_ranking_chart precisa rodar via asyncio.to_thread — chamar "
        "matplotlib direto no loop trava o bot inteiro (todas as guilds) "
        "pelo tempo de renderizacao"
    )


def test_transcript_pdf_render_does_not_block_event_loop() -> None:
    """Mesma classe de bug do painel: pisa.CreatePDF (xhtml2pdf) e sincrono e
    CPU-bound, chamado no fechamento de todo ticket — sem to_thread, travaria
    o bot inteiro a cada ticket fechado."""
    source = inspect.getsource(build_transcript_pdf)
    assert "asyncio.to_thread" in source, (
        "pisa.CreatePDF precisa rodar via asyncio.to_thread, nao direto na "
        "coroutine — senao trava o bot inteiro a cada ticket fechado"
    )


def test_backup_zip_and_copy_do_not_block_event_loop() -> None:
    """Compactacao (zipfile) e copia de transcricoes sao sincronas/IO-bound.
    Com centenas de guilds, rodar isso direto no loop travaria o bot inteiro
    pela duracao do backup diario completo, nao so da guild sendo processada."""
    source = inspect.getsource(BackupCog._backup_guild)
    assert source.count("asyncio.to_thread") >= 2, (
        "_copy_transcripts e _zip_dir precisam rodar via asyncio.to_thread — "
        "sao operacoes de arquivo sincronas que escalam com o numero de guilds"
    )
