from __future__ import annotations

import asyncio
import html
import io
from dataclasses import dataclass
from pathlib import Path

import discord
from xhtml2pdf import pisa

from database.models.ticket import Ticket

TRANSCRIPTS_DIR = Path("data/transcripts")

_PAGE_TEMPLATE = """<!doctype html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<title>Transcrição — {channel_name}</title>
<style>
  body {{ background: #313338; color: #dbdee1; font-family: "gg sans", "Segoe UI", sans-serif; margin: 0; padding: 1.5rem; }}
  .meta {{ color: #949ba4; font-size: 0.85rem; margin-bottom: 1.25rem; border-bottom: 1px solid #3f4147; padding-bottom: 1rem; }}
  .msg {{ display: flex; gap: 1rem; padding: 0.35rem 0; }}
  .avatar {{ width: 40px; height: 40px; border-radius: 50%; flex: none; }}
  .body {{ min-width: 0; }}
  .head {{ display: flex; align-items: baseline; gap: 0.5rem; }}
  .author {{ font-weight: 600; color: #f2f3f5; }}
  .time {{ font-size: 0.72rem; color: #949ba4; }}
  .content {{ white-space: pre-wrap; word-wrap: break-word; line-height: 1.4; }}
</style>
</head>
<body>
<div class="meta">
  Ticket #{ticket_short_id} · Categoria: {category} · Canal: #{channel_name}
</div>
{messages}
</body>
</html>
"""

_MESSAGE_TEMPLATE = """<div class="msg">
  <img class="avatar" src="{avatar_url}" alt="">
  <div class="body">
    <div class="head"><span class="author">{author}</span><span class="time">{timestamp}</span></div>
    <div class="content">{content}</div>
  </div>
</div>
"""

# xhtml2pdf (reportlab por baixo) so entende CSS 2.1 — sem flexbox. Layout em
# blocos simples, sem avatar (evita depender de fetch de imagem externa no render).
_PDF_PAGE_TEMPLATE = """<!doctype html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<style>
  @page {{ size: A4; margin: 1.5cm; }}
  body {{ font-family: Helvetica, sans-serif; font-size: 10pt; color: #202225; }}
  h1 {{ font-size: 14pt; margin-bottom: 0.2cm; }}
  .meta {{ font-size: 9pt; color: #555; margin-bottom: 0.6cm; border-bottom: 1px solid #ccc; padding-bottom: 0.3cm; }}
  .msg {{ margin-bottom: 0.35cm; }}
  .author {{ font-weight: bold; }}
  .time {{ font-size: 8pt; color: #888; margin-left: 0.3cm; }}
  .content {{ white-space: pre-wrap; margin-top: 0.05cm; }}
</style>
</head>
<body>
<h1>Transcrição — {channel_name}</h1>
<div class="meta">Ticket #{ticket_short_id} · Categoria: {category}</div>
{messages}
</body>
</html>
"""

_PDF_MESSAGE_TEMPLATE = """<div class="msg">
  <span class="author">{author}</span><span class="time">{timestamp}</span>
  <div class="content">{content}</div>
</div>
"""


@dataclass
class _Row:
    author: str
    avatar_url: str
    timestamp_str: str
    content_escaped: str


def _describe_extras(message: discord.Message) -> list[str]:
    """Anexos/embeds tem que aparecer na transcricao — o canal e apagado logo
    depois de gerada, entao ela e o unico registro que sobra (evidencias como
    print/comprovante enviados como anexo nao podem ser perdidas)."""
    extras: list[str] = []
    for attachment in message.attachments:
        extras.append(f"📎 <a href=\"{html.escape(attachment.url)}\">{html.escape(attachment.filename)}</a>")
    for embed in message.embeds:
        title = embed.title or embed.description or "(embed sem título)"
        extras.append(f"🔗 {html.escape(str(title))[:200]}")
    return extras


async def _collect_rows(channel: discord.TextChannel) -> list[_Row]:
    rows: list[_Row] = []
    async for message in channel.history(limit=None, oldest_first=True):
        parts = []
        if message.content:
            parts.append(html.escape(message.content))
        parts.extend(_describe_extras(message))
        content = "<br>".join(parts) if parts else "<em>(mensagem vazia)</em>"
        rows.append(
            _Row(
                author=html.escape(str(message.author.display_name)),
                avatar_url=message.author.display_avatar.url,
                timestamp_str=message.created_at.strftime("%d/%m/%Y %H:%M"),
                content_escaped=content,
            )
        )
    return rows


async def build_transcript_html(channel: discord.TextChannel, ticket: Ticket) -> str:
    """Gera um HTML estatico parecido com o chat do Discord, com autor/horario
    de cada mensagem do canal — usado antes de excluir o canal do ticket."""
    rows = await _collect_rows(channel)
    messages = "".join(
        _MESSAGE_TEMPLATE.format(
            avatar_url=row.avatar_url,
            author=row.author,
            timestamp=row.timestamp_str,
            content=row.content_escaped,
        )
        for row in rows
    )
    return _PAGE_TEMPLATE.format(
        channel_name=html.escape(channel.name),
        ticket_short_id=str(ticket.id)[:8],
        category=ticket.category.value,
        messages=messages or "<p>Nenhuma mensagem neste canal.</p>",
    )


async def build_transcript_pdf(channel: discord.TextChannel, ticket: Ticket) -> bytes:
    """Gera o mesmo historico em PDF (layout simplificado, sem avatar)."""
    rows = await _collect_rows(channel)
    messages = "".join(
        _PDF_MESSAGE_TEMPLATE.format(
            author=row.author, timestamp=row.timestamp_str, content=row.content_escaped
        )
        for row in rows
    )
    pdf_html = _PDF_PAGE_TEMPLATE.format(
        channel_name=html.escape(channel.name),
        ticket_short_id=str(ticket.id)[:8],
        category=ticket.category.value,
        messages=messages or "<p>Nenhuma mensagem neste canal.</p>",
    )

    return await asyncio.to_thread(_render_pdf, pdf_html)


def _render_pdf(pdf_html: str) -> bytes:
    # xhtml2pdf e sincrono/CPU-bound — rodar direto no loop bloquearia o bot
    # inteiro (todas as guilds) pelo tempo de renderizacao a cada ticket
    # fechado, entao isso precisa rodar numa thread separada.
    buffer = io.BytesIO()
    pisa.CreatePDF(pdf_html, dest=buffer)
    return buffer.getvalue()


def save_transcript_locally(ticket: Ticket, html_content: str, pdf_content: bytes) -> None:
    """Guarda uma copia local (html+pdf) pra entrar no backup diario — os
    canais de ticket sao apagados depois do fechamento, entao esse e o unico
    registro que sobrevive alem do que foi mandado pro Discord.

    O arquivo usa o UUID completo do ticket (nao so os 8 primeiros chars) —
    a pasta e compartilhada entre TODAS as guilds do bot, e um prefixo curto
    tem chance real de colisao entre tickets de guilds diferentes conforme o
    volume cresce, o que faria a transcricao de um cliente sobrescrever a de
    outro silenciosamente."""
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    file_id = str(ticket.id)
    (TRANSCRIPTS_DIR / f"{file_id}.html").write_text(html_content, encoding="utf-8")
    (TRANSCRIPTS_DIR / f"{file_id}.pdf").write_bytes(pdf_content)
