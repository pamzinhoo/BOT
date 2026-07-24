from __future__ import annotations

import discord

from database.models.audit_log import AuditLogCategory
from database.models.log import LogAction
from database.models.ticket import TicketCategory

CATEGORY_LABELS: dict[TicketCategory, str] = {
    TicketCategory.BUG: "🐛 Bug",
    TicketCategory.DENUNCIA: "🚨 Denúncia",
    TicketCategory.DUVIDA: "❓ Dúvida",
    TicketCategory.SUGESTAO: "💡 Sugestão",
    TicketCategory.PARCERIA: "🤝 Parceria",
    TicketCategory.OUTRO: "📁 Outro",
}

CATEGORY_CONFIRM_TEXT: dict[TicketCategory, str] = {
    TicketCategory.PARCERIA: (
        "🤝 **Candidatura para Parceiro / Streamer**\n\n"
        "Obrigado pelo interesse em fazer parte do nosso programa de parceiros!\n\n"
        "Ao abrir este ticket, nossa equipe irá analisar sua candidatura. Durante o "
        "atendimento, envie os links das suas redes sociais/plataformas de conteúdo e "
        "responda às perguntas da equipe.\n\n"
        "**Importante:**\n"
        "- Envie apenas informações verdadeiras.\n"
        "- A aprovação depende da análise da equipe.\n"
        "- O envio da candidatura **não garante** que você será aceito.\n\n"
        "Boa sorte! 💙"
    ),
    TicketCategory.SUGESTAO: (
        "💡 **Sugestões para o Servidor**\n\n"
        "Tem uma ideia que pode tornar o servidor ainda melhor? Abra um ticket e "
        "compartilhe sua sugestão.\n\n"
        "Explique com detalhes:\n"
        "- O que você gostaria de sugerir;\n"
        "- Como a ideia funcionaria;\n"
        "- Quais benefícios ela traria para o servidor e para os jogadores.\n\n"
        "Todas as sugestões são analisadas pela equipe, mas a implementação dependerá "
        "da viabilidade e do impacto no servidor."
    ),
    TicketCategory.BUG: (
        "🐞 **Reporte um Bug**\n\n"
        "Encontrou algum erro no servidor? Abra um ticket e informe o máximo de "
        "detalhes possível.\n\n"
        "Sempre que possível, anexe um vídeo do problema. Caso não tenha um vídeo, "
        "envie prints nítidas.\n\n"
        "Inclua também:\n"
        "- 📝 O que aconteceu;\n"
        "- 🔄 Como reproduzir o bug (passo a passo);\n"
        "- 📍 Onde o bug ocorreu;\n"
        "- ⏰ Data e horário aproximados.\n\n"
        "Quanto mais informações você fornecer, mais rápido conseguiremos identificar "
        "e corrigir o problema."
    ),
    TicketCategory.DUVIDA: (
        "❓ **Dúvidas**\n\n"
        "Abra um ticket para falar diretamente com nossa equipe de suporte. Informe "
        "sua dúvida com o máximo de detalhes possível para que possamos oferecer um "
        "atendimento rápido e preciso."
    ),
    TicketCategory.DENUNCIA: (
        "📢 **Antes de criar sua denúncia**\n\n"
        "Para que ela seja analisada, envie o máximo de informações possível.\n\n"
        "Preferencialmente anexe um vídeo do ocorrido, pois ele mostra todo o "
        "contexto da situação. Caso não tenha um vídeo, envie prints legíveis.\n\n"
        "Inclua também:\n"
        "- Nome(s) do(s) jogador(es) envolvido(s);\n"
        "- Data e horário aproximados;\n"
        "- Descrição clara do ocorrido.\n\n"
        "Denúncias sem provas ou com informações insuficientes poderão ser "
        "encerradas sem punição por falta de evidências."
    ),
    TicketCategory.OUTRO: (
        "📁 **Outro assunto**\n\n"
        "Abra um ticket e descreva com detalhes o que você precisa. Nossa equipe vai "
        "analisar e responder o quanto antes."
    ),
}

LOG_ACTION_LABELS: dict[LogAction, str] = {
    LogAction.CLAIM: "Claim",
    LogAction.UNCLAIM: "Unclaim",
    LogAction.FECHAMENTO: "Fechamento",
    LogAction.AVALIACAO: "Avaliação",
    LogAction.RANKING_ALTERADO: "Alteração no ranking",
    LogAction.ERRO: "Erro",
    LogAction.ATUALIZACAO_AUTOMATICA: "Atualização automática",
    LogAction.CONFIG_ALTERADA: "Alteração de configuração",
    LogAction.REABERTURA: "Reabertura",
    LogAction.SPAM_DETECTADO: "Spam detectado",
    LogAction.BLACKLIST_ACAO: "Ação de blacklist",
}

ACHIEVEMENT_LABELS: dict[str, str] = {
    "first_ticket": "🏆 Primeiro Ticket",
    "tickets_100": "🏆 100 Tickets",
    "tickets_1000": "🏆 1000 Tickets",
    "five_star": "🏆 Nota 5★",
    "clean_30_days": "🏆 30 dias sem avaliação ruim",
}

MEDALS = ["🥇", "🥈", "🥉"]


def achievement_label(key: str) -> str:
    if key.startswith("monthly_top1_"):
        year, month = key.removeprefix("monthly_top1_").split("-")
        return f"🏆 1º lugar do mês {month}/{year}"
    return ACHIEVEMENT_LABELS.get(key, f"🏆 {key}")

EMBED_COLOR_DEFAULT = discord.Color.blurple()
EMBED_COLOR_SUCCESS = discord.Color.green()
EMBED_COLOR_WARNING = discord.Color.yellow()
EMBED_COLOR_DANGER = discord.Color.red()
EMBED_COLOR_ORANGE = discord.Color.orange()
EMBED_COLOR_INFO = discord.Color.blue()
EMBED_COLOR_PURPLE = discord.Color.purple()
EMBED_COLOR_VIOLET = discord.Color.dark_purple()
EMBED_COLOR_DARK = discord.Color.dark_grey()

TICKET_IMMEDIATE_CLOSE_SECONDS = 30
TICKET_AUTO_DELETE_SECONDS = 10

AUDIT_CATEGORY_LABELS: dict[AuditLogCategory, str] = {
    AuditLogCategory.BAN: "🔨 Banimento",
    AuditLogCategory.KICK: "👢 Expulsão",
    AuditLogCategory.TIMEOUT: "⏳ Timeout",
    AuditLogCategory.ROLE_UPDATE: "🎭 Alteração de Cargos",
    AuditLogCategory.NICKNAME: "✏️ Apelido Alterado",
    AuditLogCategory.CHANNEL_UPDATE: "🔧 Canal Alterado",
    AuditLogCategory.CATEGORY_UPDATE: "🗂️ Categoria Alterada",
    AuditLogCategory.PERMISSION_UPDATE: "🔐 Permissões Alteradas",
    AuditLogCategory.CHANNEL_CREATE_DELETE: "📺 Canal Criado/Removido",
    AuditLogCategory.ROLE_CREATE_DELETE: "🏷️ Cargo Criado/Removido",
    AuditLogCategory.MESSAGE_DELETE: "🗑️ Mensagem Apagada",
    AuditLogCategory.MESSAGE_EDIT: "📝 Mensagem Editada",
    AuditLogCategory.BULK_DELETE: "🧹 Bulk Delete",
    AuditLogCategory.VOICE_JOIN_LEAVE: "🔊 Entrada/Saída de Call",
    AuditLogCategory.VOICE_MOVE: "🔀 Movimentação de Call",
    AuditLogCategory.MUTE_UNMUTE: "🔇 Mute/Unmute",
    AuditLogCategory.DEAF_UNDEAF: "🙉 Deaf/Undeaf",
    AuditLogCategory.BOT_ADDED: "🤖 Bot",
    AuditLogCategory.EMOJI: "😀 Emoji",
    AuditLogCategory.STICKER: "🏷️ Sticker",
    AuditLogCategory.SERVER_CONFIG: "⚙️ Configuração do Servidor",
    AuditLogCategory.TICKETS: "🎫 Ticket",
}

# como montar a mencao do alvo no embed/lista: "user" -> <@id>, "channel" -> <#id>,
# "role" -> <@&id>, "none" -> so o nome (emoji/sticker nao sao mencionaveis)
AUDIT_CATEGORY_TARGET_KIND: dict[AuditLogCategory, str] = {
    AuditLogCategory.BAN: "user",
    AuditLogCategory.KICK: "user",
    AuditLogCategory.TIMEOUT: "user",
    AuditLogCategory.ROLE_UPDATE: "user",
    AuditLogCategory.NICKNAME: "user",
    AuditLogCategory.CHANNEL_UPDATE: "channel",
    AuditLogCategory.CATEGORY_UPDATE: "channel",
    AuditLogCategory.PERMISSION_UPDATE: "channel",
    AuditLogCategory.CHANNEL_CREATE_DELETE: "channel",
    AuditLogCategory.ROLE_CREATE_DELETE: "role",
    AuditLogCategory.MESSAGE_DELETE: "user",
    AuditLogCategory.MESSAGE_EDIT: "user",
    AuditLogCategory.BULK_DELETE: "channel",
    AuditLogCategory.VOICE_JOIN_LEAVE: "user",
    AuditLogCategory.VOICE_MOVE: "user",
    AuditLogCategory.MUTE_UNMUTE: "user",
    AuditLogCategory.DEAF_UNDEAF: "user",
    AuditLogCategory.BOT_ADDED: "user",
    AuditLogCategory.EMOJI: "none",
    AuditLogCategory.STICKER: "none",
    AuditLogCategory.SERVER_CONFIG: "none",
    AuditLogCategory.TICKETS: "channel",
}

AUDIT_CATEGORY_COLORS: dict[AuditLogCategory, discord.Color] = {
    AuditLogCategory.BAN: EMBED_COLOR_DANGER,
    AuditLogCategory.KICK: EMBED_COLOR_ORANGE,
    AuditLogCategory.TIMEOUT: EMBED_COLOR_WARNING,
    AuditLogCategory.ROLE_UPDATE: EMBED_COLOR_SUCCESS,
    AuditLogCategory.NICKNAME: EMBED_COLOR_SUCCESS,
    AuditLogCategory.CHANNEL_UPDATE: EMBED_COLOR_INFO,
    AuditLogCategory.CATEGORY_UPDATE: EMBED_COLOR_INFO,
    AuditLogCategory.PERMISSION_UPDATE: EMBED_COLOR_INFO,
    AuditLogCategory.CHANNEL_CREATE_DELETE: EMBED_COLOR_INFO,
    AuditLogCategory.ROLE_CREATE_DELETE: EMBED_COLOR_SUCCESS,
    AuditLogCategory.MESSAGE_DELETE: EMBED_COLOR_DEFAULT,
    AuditLogCategory.MESSAGE_EDIT: EMBED_COLOR_DEFAULT,
    AuditLogCategory.BULK_DELETE: EMBED_COLOR_DEFAULT,
    AuditLogCategory.VOICE_JOIN_LEAVE: EMBED_COLOR_VIOLET,
    AuditLogCategory.VOICE_MOVE: EMBED_COLOR_VIOLET,
    AuditLogCategory.MUTE_UNMUTE: EMBED_COLOR_VIOLET,
    AuditLogCategory.DEAF_UNDEAF: EMBED_COLOR_VIOLET,
    AuditLogCategory.BOT_ADDED: EMBED_COLOR_DEFAULT,
    AuditLogCategory.EMOJI: EMBED_COLOR_DEFAULT,
    AuditLogCategory.STICKER: EMBED_COLOR_DEFAULT,
    AuditLogCategory.SERVER_CONFIG: EMBED_COLOR_DARK,
    AuditLogCategory.TICKETS: EMBED_COLOR_PURPLE,
}
