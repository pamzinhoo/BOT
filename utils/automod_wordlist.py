from __future__ import annotations

import re
import unicodedata

from database.models.automod import AutoModCategory, AutoModRiskLevel

# mapa de substituicao leetspeak -> letra original (aplicado antes de remover
# pontuacao, pra pegar "1d10t4" -> "idiota" e "@" -> "a")
_LEET_MAP = str.maketrans(
    {
        "0": "o",
        "1": "i",
        "3": "e",
        "4": "a",
        "5": "s",
        "7": "t",
        "8": "b",
        "@": "a",
        "$": "s",
    }
)

# qualquer caractere que nao seja letra/digito/espaco e removido (nao substituido
# por espaco) — isso e o que faz "i.d.i.o.t.a" virar "idiota" mantendo "cala a
# boca" com os espacos intactos.
_NON_ALNUM_SPACE = re.compile(r"[^a-z0-9\s]")
_MULTI_SPACE = re.compile(r"\s+")


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_text(text: str) -> str:
    """Normaliza mensagem pra deteccao: lowercase, sem acento, leetspeak resolvido,
    pontuacao removida (nao virou espaco), espacos colapsados."""
    lowered = text.lower()
    no_accents = _strip_accents(lowered)
    leet_resolved = no_accents.translate(_LEET_MAP)
    no_punctuation = _NON_ALNUM_SPACE.sub("", leet_resolved)
    return _MULTI_SPACE.sub(" ", no_punctuation).strip()


def compact_form(normalized: str) -> str:
    """Forma sem nenhum espaco — usada como segunda tentativa pra termos curtos
    que o autor tenta burlar espacando letra por letra com espaco real."""
    return normalized.replace(" ", "")


# palavras que NUNCA devem gerar punicao automatica sozinhas — apenas marcadas
# como suspeitas pro contexto/staff analisarem, evitando falso positivo.
CONTEXT_SENSITIVE_WORDS: set[str] = {"preto", "negro"}

# (palavra normalizada, categoria, nivel)
DEFAULT_AUTOMOD_WORDS: list[tuple[str, AutoModCategory, AutoModRiskLevel]] = [
    # Ofensas — baixo risco
    ("idiota", AutoModCategory.OFENSA, AutoModRiskLevel.BAIXO),
    ("burro", AutoModCategory.OFENSA, AutoModRiskLevel.BAIXO),
    ("lixo", AutoModCategory.OFENSA, AutoModRiskLevel.BAIXO),
    ("inutil", AutoModCategory.OFENSA, AutoModRiskLevel.BAIXO),
    ("retardado", AutoModCategory.OFENSA, AutoModRiskLevel.BAIXO),
    ("imbecil", AutoModCategory.OFENSA, AutoModRiskLevel.BAIXO),
    ("otario", AutoModCategory.OFENSA, AutoModRiskLevel.BAIXO),
    ("babaca", AutoModCategory.OFENSA, AutoModRiskLevel.BAIXO),
    ("trouxa", AutoModCategory.OFENSA, AutoModRiskLevel.BAIXO),
    ("escroto", AutoModCategory.OFENSA, AutoModRiskLevel.BAIXO),
    ("nojento", AutoModCategory.OFENSA, AutoModRiskLevel.BAIXO),
    ("mkk", AutoModCategory.OFENSA, AutoModRiskLevel.BAIXO),
    ("mcc", AutoModCategory.OFENSA, AutoModRiskLevel.BAIXO),
    ("filha da puta", AutoModCategory.OFENSA, AutoModRiskLevel.BAIXO),
    ("fdp", AutoModCategory.OFENSA, AutoModRiskLevel.BAIXO),
    ("pau no cu", AutoModCategory.OFENSA, AutoModRiskLevel.BAIXO),
    ("vagabundo", AutoModCategory.OFENSA, AutoModRiskLevel.BAIXO),
    ("escravo", AutoModCategory.OFENSA, AutoModRiskLevel.BAIXO),
    ("vadia", AutoModCategory.OFENSA, AutoModRiskLevel.BAIXO),
    # Discriminacao / ataques a grupos protegidos — alto risco (hate speech)
    ("macaco", AutoModCategory.DISCRIMINACAO, AutoModRiskLevel.ALTO),
    ("neguinho", AutoModCategory.DISCRIMINACAO, AutoModRiskLevel.ALTO),
    # termos sensiveis ao contexto — NAO punem sozinhos (ver CONTEXT_SENSITIVE_WORDS)
    ("preto", AutoModCategory.SUSPEITA, AutoModRiskLevel.BAIXO),
    ("negro", AutoModCategory.SUSPEITA, AutoModRiskLevel.BAIXO),
    # Golpes e spam — medio risco
    ("free nitro", AutoModCategory.GOLPE_SPAM, AutoModRiskLevel.MEDIO),
    ("nitro gratis", AutoModCategory.GOLPE_SPAM, AutoModRiskLevel.MEDIO),
    ("clique aqui", AutoModCategory.GOLPE_SPAM, AutoModRiskLevel.MEDIO),
    ("ganhei nitro", AutoModCategory.GOLPE_SPAM, AutoModRiskLevel.MEDIO),
    ("gift", AutoModCategory.GOLPE_SPAM, AutoModRiskLevel.MEDIO),
    ("giveaway falso", AutoModCategory.GOLPE_SPAM, AutoModRiskLevel.MEDIO),
    ("steam gift", AutoModCategory.GOLPE_SPAM, AutoModRiskLevel.MEDIO),
    ("crypto gratis", AutoModCategory.GOLPE_SPAM, AutoModRiskLevel.MEDIO),
    ("investimento garantido", AutoModCategory.GOLPE_SPAM, AutoModRiskLevel.MEDIO),
    ("dinheiro facil", AutoModCategory.GOLPE_SPAM, AutoModRiskLevel.MEDIO),
    ("dinheiro rapido", AutoModCategory.GOLPE_SPAM, AutoModRiskLevel.MEDIO),
    # Conteudo sexual ilegal — alto risco
    ("porno", AutoModCategory.SEXUAL_ILEGAL, AutoModRiskLevel.ALTO),
    ("pornografia", AutoModCategory.SEXUAL_ILEGAL, AutoModRiskLevel.ALTO),
    ("pornografia infantil", AutoModCategory.SEXUAL_ILEGAL, AutoModRiskLevel.ALTO),
    ("cp", AutoModCategory.SEXUAL_ILEGAL, AutoModRiskLevel.ALTO),
    # Privacidade e seguranca — alto risco
    ("endereco", AutoModCategory.PRIVACIDADE, AutoModRiskLevel.ALTO),
    ("telefone", AutoModCategory.PRIVACIDADE, AutoModRiskLevel.ALTO),
    ("cpf", AutoModCategory.PRIVACIDADE, AutoModRiskLevel.ALTO),
    ("senha", AutoModCategory.PRIVACIDADE, AutoModRiskLevel.ALTO),
    ("ip", AutoModCategory.PRIVACIDADE, AutoModRiskLevel.ALTO),
    ("vazamento", AutoModCategory.PRIVACIDADE, AutoModRiskLevel.ALTO),
    ("doxx", AutoModCategory.PRIVACIDADE, AutoModRiskLevel.ALTO),
    ("exposicao de dados pessoais", AutoModCategory.PRIVACIDADE, AutoModRiskLevel.ALTO),
    ("pedido de informacoes privadas", AutoModCategory.PRIVACIDADE, AutoModRiskLevel.ALTO),
    # Ameacas e assedio
    ("ameaca", AutoModCategory.AMEACA_ASSEDIO, AutoModRiskLevel.ALTO),
    ("chantagem", AutoModCategory.AMEACA_ASSEDIO, AutoModRiskLevel.ALTO),
    ("perseguicao", AutoModCategory.AMEACA_ASSEDIO, AutoModRiskLevel.ALTO),
    ("cala a boca", AutoModCategory.AMEACA_ASSEDIO, AutoModRiskLevel.MEDIO),
    ("vai se foder", AutoModCategory.AMEACA_ASSEDIO, AutoModRiskLevel.MEDIO),
    ("vai se fuder", AutoModCategory.AMEACA_ASSEDIO, AutoModRiskLevel.MEDIO),
]

# conteudo cuja gravidade exige resposta maxima independente da config da guild
# (CSAM) — sempre trata como alto risco e sinaliza urgencia no alerta pra staff.
CRITICAL_WORDS: set[str] = {"pornografia infantil", "cp"}

# palavras normalizadas -> (categoria, nivel), pra lookup O(1)
DEFAULT_WORDS_BY_TEXT: dict[str, tuple[AutoModCategory, AutoModRiskLevel]] = {
    word: (category, level) for word, category, level in DEFAULT_AUTOMOD_WORDS
}
