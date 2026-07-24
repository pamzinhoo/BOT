# BOT LIMERENCE

Plataforma de gerenciamento da equipe de suporte do Discord (tickets, claim, ranking, avaliacoes, relatorios).

## Status

**Fase 1 concluida:** estrutura do projeto, config, logging, camada de banco (SQLAlchemy async + Alembic), inicializacao do bot.
Nenhuma feature de negocio (claim, ranking, etc.) foi implementada ainda — isso comeca na Fase 2.

## Stack

- Python 3.13+
- discord.py 2.x
- PostgreSQL + asyncpg
- SQLAlchemy 2.x (async)
- Alembic
- python-dotenv

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt

copy .env.example .env
# edite .env com DISCORD_TOKEN e DATABASE_URL reais
```

Crie o banco PostgreSQL antes de rodar:

```sql
CREATE DATABASE bot_limerence;
```

## Migrations

```bash
alembic revision --autogenerate -m "descricao da mudanca"
alembic upgrade head
```

`alembic/env.py` le `DATABASE_URL` do `.env` automaticamente e usa `Base.metadata`
de `database/models/` como fonte de verdade para o autogenerate.

## Rodando o bot

```bash
python main.py
```

## Estrutura

```
core/            bot (LimerenceBot), logger
config/          settings.py (carrega e valida .env)
database/        engine/sessao async, models/, repositories/
cogs/            comandos slash (carregados automaticamente por core/bot.py)
services/        regras de negocio, chamadas pelos cogs
views/           embeds, botoes, modals, dropdowns
utils/           helpers genericos
alembic/         migrations
logs/            bot.log, error.log (rotacionados, 5MB x5)
```

Para adicionar uma feature nova: model em `database/models/`, repositorio em
`database/repositories/`, regra de negocio em `services/`, comando em `cogs/`.
Nenhum modulo existente precisa ser alterado para isso.

## Proximas fases

- Fase 2: `/claim`, ranking, painel, banco do claim
- Fase 3: `/staff`, `/status`, atividade
- Fase 4: avaliacoes, botoes, estatisticas
- Fase 5: relatorios automaticos, dashboard, logs avancados
- Fase 6: testes, otimizacao, documentacao
