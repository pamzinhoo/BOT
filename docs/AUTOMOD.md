# AutoMod

Moderação automática de mensagens: detecta conteúdo proibido (ofensas, discriminação,
golpes/spam, conteúdo sexual ilegal, dados privados, ameaças/assédio), apaga a
mensagem e aplica a ação configurada (aviso, timeout ou ban) de acordo com o nível
de risco. Tudo fica registrado em `automod_logs`.

## Arquitetura

- `database/models/automod.py` — `AutoModWord` (tabela `automod_config`),
  `AutoModSettings` (`automod_settings`), `AutoModLog` (`automod_logs`).
- `database/repositories/automod_repository.py` — repositórios CRUD.
- `utils/automod_wordlist.py` — lista padrão embutida no código (não no banco) +
  normalização de texto anti-bypass.
- `services/automod_service.py` — detecção, pontuação de risco e aplicação de ações
  no Discord (segue o mesmo padrão do `PunishmentService`).
- `cogs/automod.py` — `/automod` (comandos) + listener `on_message`.

A lista padrão de palavras vive em código (`DEFAULT_AUTOMOD_WORDS`), não no banco —
o banco (`automod_config`) só guarda **overrides por guild**: palavras
personalizadas adicionadas (`is_builtin=False`) e supressões de palavras padrão
(`is_builtin=True, active=False`, criado por `/automod remover` numa palavra padrão).

## Normalização anti-bypass

Antes de comparar com a lista de palavras, a mensagem passa por
`normalize_text()`:

1. lowercase
2. remove acentos (`á` → `a`)
3. resolve leetspeak (`0→o 1→i 3→e 4→a 5→s 7→t 8→b @→a $→s`)
4. remove pontuação (sem virar espaço — é isso que junta letras separadas)
5. colapsa espaços múltiplos

Exemplos:

| Entrada | Normalizado |
|---|---|
| `1d10t4` | `idiota` |
| `i.d.i.o.t.a` | `idiota` |
| `f.d.p` | `fdp` |
| `Vai se FODER!!` | `vai se foder` |

Termos com espaço (`"free nitro"`, `"cala a boca"`) são comparados como frase
(com limite de palavra). Termos de uma palavra só também são comparados contra a
versão sem nenhum espaço (`compact_form`), pra pegar `"f d p"` digitado com
espaço real — restrito a termos com 4+ caracteres pra evitar falso positivo em
substrings curtas.

## Contexto — "preto" / "negro"

Essas palavras nunca punem sozinhas: entram como categoria `SUSPEITA`,
nível `BAIXO`, e são só **sinalizadas** (`automod_logs.punicao_aplicada =
"sinalizada_para_revisao"`, mensagem não é apagada). Se aparecerem na mesma
mensagem junto de um termo realmente discriminatório (ex.: `"macaco"`), o
sistema ignora o sinalizador e pune pelo termo discriminatório normalmente.

## Pontuação de risco

| Nível | Categorias | Ação padrão |
|---|---|---|
| Baixo | Ofensa simples | Apaga mensagem + aviso no canal (auto-apaga em 8s) |
| Médio | Golpe/spam, assédio leve (`cala a boca`, `vai se foder`) | Apaga + timeout configurável (padrão 10 min) + log |
| Alto | Discriminação, sexual ilegal, privacidade/doxxing, ameaça/perseguição/chantagem | Apaga + timeout maior (padrão 24h) **ou** ban (config) + alerta no canal de mods + log |

Conteúdo em `CRITICAL_WORDS` (`"pornografia infantil"`, `"cp"`) sempre marca o
alerta de mods como urgente (🚨), independente da configuração de ban/timeout.

## Comandos

Todos exigem permissão de Administrador do bot (`is_admin()` — Administrador do
Discord ou cargo Owner/Dev/CEO configurado em `/config`).

### `/automod ativar estado:<Ligar|Desligar>`
Liga/desliga o AutoMod nesta guild. Desativado por padrão.

### `/automod adicionar palavra:<texto> [categoria] [nivel]`
Adiciona palavra/expressão personalizada. `categoria` e `nivel` são opcionais
(padrão: Personalizada / Baixo). Se a palavra já existir como override da guild,
atualiza categoria/nível.

```
/automod adicionar palavra:"golpe do pix" categoria:Golpe/Spam nivel:Médio
```

### `/automod remover palavra:<texto>`
Remove uma palavra personalizada, ou suprime uma palavra da lista padrão só
nesta guild (ex.: liberar `"lixo"` num servidor de reciclagem).

```
/automod remover palavra:lixo
```

### `/automod lista`
Mostra todas as palavras ativas (padrão + personalizadas) agrupadas por
categoria, com o nível de cada uma.

### `/automod configurar [opções]`
Configura punições e exceções. Todos os parâmetros são opcionais — só altera o
que for informado; chamado sem parâmetros mostra a config atual.

```
/automod configurar timeout_medio_minutos:15 timeout_alto_minutos:2880
/automod configurar usar_ban_alto_risco:True canal_alerta:#mod-alertas
/automod configurar canal_ignorado:#staff-chat
/automod configurar cargo_ignorado:@Staff
```

Exceções de palavra (`allowed_words`, ex.: liberar `"preto"` num canal de
discussão específico) hoje são setadas direto via `AutoModService.update_settings`
— não há subcomando dedicado; pode ser adicionado depois se necessário.

### `/automod logs [quantidade]`
Mostra o histórico de ações automáticas mais recentes (padrão 20, máx. 50):
usuário, termo detectado, categoria, nível e ação aplicada.

## Exemplo de configuração inicial

```
/automod ativar estado:Ligar
/automod configurar timeout_medio_minutos:10 timeout_alto_minutos:1440 canal_alerta:#mod-log
/automod configurar cargo_ignorado:@Staff
/automod adicionar palavra:"invadir conta" categoria:Ameaça/Assédio nivel:Alto
```

## Migração

`alembic/versions/a3c7f1e9b2d4_sistema_de_automod.py` cria `automod_config`,
`automod_settings` e `automod_logs`. Rode `alembic upgrade head`.

## Testes

- `tests/test_automod_normalization.py` — normalização (acentos, leetspeak,
  separadores, preservação de frases).
- `tests/test_automod_service.py` — deteção/pontuação (`AutoModService.analyze`):
  baixo/médio/alto risco, contexto sensível (`preto`/`negro`), escalonamento por
  combinação, exceções (`allowed_words`).
