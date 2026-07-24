# Schema do banco — proposta para revisão (pré-Fase 2)

Convenção adotada: **PK interna = UUID** (`gen_random_uuid()`, nativo no Postgres
desde a v13 — sem precisar de extensão). **IDs do Discord (guild/canal/usuário/
mensagem) = BIGINT**, pois já chegam como snowflakes inteiros da API.

## Diagrama

```mermaid
erDiagram
    STAFF ||--o{ CLAIMS : "reivindica"
    STAFF ||--o| STAFF_STATS : "agrega"
    STAFF ||--o{ STAFF_ACTIVITY : "gera"
    STAFF ||--o{ EVALUATIONS : "recebe"
    STAFF ||--o{ TICKETS : "atende (claimed_by)"

    TICKETS ||--o{ CLAIMS : "historico"
    TICKETS ||--o{ TICKET_MESSAGES : "contem"
    TICKETS ||--o| EVALUATIONS : "avaliado_em"
    TICKETS ||--o{ LOGS : "referencia"

    GUILD_SETTINGS ||--o{ RANKING_CACHE : "por_guild"

    STAFF {
        uuid id PK
        bigint guild_id
        bigint discord_user_id
        string display_name
        bool active
        timestamptz created_at
        timestamptz updated_at
    }

    TICKETS {
        uuid id PK
        bigint guild_id
        bigint channel_id UK
        bigint opened_by_discord_id
        enum category
        enum status
        uuid claimed_by_staff_id FK
        timestamptz first_response_at
        timestamptz closed_at
        bigint closed_by_discord_id
        bool deleted_before_service
        timestamptz created_at
        timestamptz updated_at
    }

    CLAIMS {
        uuid id PK
        uuid ticket_id FK
        uuid staff_id FK
        timestamptz claimed_at
        timestamptz unclaimed_at
        timestamptz created_at
    }

    TICKET_MESSAGES {
        uuid id PK
        uuid ticket_id FK
        bigint discord_message_id UK
        bigint author_discord_id
        bool author_is_staff
        timestamptz sent_at
    }

    STAFF_STATS {
        uuid id PK
        uuid staff_id FK UK
        int tickets_assumidos
        int tickets_fechados
        int tickets_cancelados
        int avaliacoes_count
        numeric avaliacao_media
        smallint melhor_avaliacao
        smallint pior_avaliacao
        int tempo_medio_primeira_resposta_s
        int tempo_medio_fechamento_s
        timestamptz primeiro_ticket_at
        timestamptz ultimo_ticket_at
        uuid ticket_atual_id FK
        timestamptz updated_at
    }

    STAFF_ACTIVITY {
        uuid id PK
        uuid staff_id FK
        enum event_type
        timestamptz occurred_at
    }

    EVALUATIONS {
        uuid id PK
        uuid ticket_id FK UK
        uuid staff_id FK
        bigint rated_by_discord_id
        smallint rating
        text comment
        timestamptz created_at
    }

    RANKING_CACHE {
        uuid id PK
        bigint guild_id
        enum period
        jsonb payload
        timestamptz generated_at
    }

    GUILD_SETTINGS {
        uuid id PK
        bigint guild_id UK
        bigint log_channel_id
        bigint ranking_channel_id
        bigint reports_channel_id
        bigint evaluations_channel_id
        bigint moderator_role_id
        bigint dev_role_id
        bigint ceo_role_id
        int inactive_after_minutes
        jsonb extra_config
        timestamptz updated_at
    }

    LOGS {
        uuid id PK
        bigint guild_id
        enum action
        bigint actor_discord_id
        uuid staff_id FK
        uuid ticket_id FK
        string category_snapshot
        text message
        timestamptz created_at
    }
```

## Notas de design

**staff** — identidade (1 linha por membro da staff por guild). Estatísticas
ficam fora, em `staff_stats`, pra não misturar dado de identidade com dado
recalculável. `unique(guild_id, discord_user_id)`.

**tickets** — 1 linha por ticket. `channel_id` é `UNIQUE` (1 canal = 1 ticket).
`status` cobre `open/claimed/closed/cancelled`; `deleted_before_service` é a
flag de anti-fraude pra "ticket excluído antes do atendimento".

**claims** — histórico completo de claim/unclaim (N por ticket, já que um
ticket pode trocar de responsável). É daqui que sai a regra anti-fraude
"ticket já teve claim anteriormente" e o cálculo de tempo até resposta.

**ticket_messages** — existe só pra sustentar duas regras de anti-fraude
("fechado sem receber mensagem do usuário", "fechado imediatamente") e o
cálculo de tempo de primeira resposta. Guarda metadado, não o conteúdo da
mensagem (não precisa pra estatística e evita lidar com dado sensível à toa).

**staff_stats** — 1 linha por staff, atualizada incrementalmente pelos
services quando um ticket fecha ou uma avaliação chega. Evita recalcular tudo
via `COUNT`/`AVG` a cada `/staff`.

**evaluations** — `unique(ticket_id)` é a trava de "só pode avaliar 1 vez por
ticket" a nível de banco, não só de aplicação.

**ranking_cache** — snapshot serializado (`jsonb`) por guild+período, gerado
pelos relatórios automáticos (Fase 5) e consumido pelo painel fixo (Fase 2/4)
sem recalcular ranking a cada mensagem.

**guild_settings** — 1 linha por guild com todos os IDs configuráveis do
spec (canais, cargos, tempo de inatividade). `extra_config jsonb` é a válvula
de escape pra configs futuras sem precisar de migration nova toda vez.

**logs** — tabela de auditoria, cobre os 8 tipos de evento pedidos (claim,
unclaim, fechamento, avaliação, alteração de ranking, erro, atualização
automática, alteração de config). `category_snapshot` é `string`, não FK pro
enum de `tickets.category`, porque o log tem que sobreviver mesmo se o ticket
for apagado depois.

## Índices previstos (além das PKs/UKs acima)

- `tickets(guild_id, status)` — listagens de abertos por guild
- `claims(staff_id, claimed_at)` — histórico de um staff, ordenado
- `staff_activity(staff_id, occurred_at)` — cálculo de inatividade
- `logs(guild_id, created_at)` — consulta de log recente por guild

## Cascade / FK behavior

- `tickets.claimed_by_staff_id` → `staff.id`: `ON DELETE SET NULL` (perder o
  staff não pode apagar o ticket)
- `claims.ticket_id` / `claims.staff_id` → `ON DELETE CASCADE` (histórico só
  faz sentido junto do ticket/staff)
- `ticket_messages.ticket_id` → `ON DELETE CASCADE`
- `evaluations.ticket_id` / `evaluations.staff_id` → `ON DELETE CASCADE`
- `logs.*_id` → `ON DELETE SET NULL` (log tem que sobreviver)

## O que fica pra decidir com você antes de eu gerar os models

1. `staff_activity` guarda todo evento (`online/offline/idle`) ou só
   claim/unclaim/closed? Guardar presença completa cresce muito rápido
   (potencialmente milhares de linhas/dia por staff).
2. `ranking_cache.period` cobre `daily/weekly/monthly/alltime` — confirma que
   "ranking ao vivo" do painel (Fase 2) também lê daqui, ou ele calcula
   on-the-fly a partir de `staff_stats`?
3. `ticket_messages` guarda 1 linha por mensagem do ticket inteiro, ou só a
   primeira mensagem do usuário e a primeira resposta da staff (bem mais
   leve)?
