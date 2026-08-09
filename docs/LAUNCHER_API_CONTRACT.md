# Contrato de API — Launcher (Fase 4)

Implementação de `bot/docs/LIMERENCE_LAUNCHER_ARCHITECTURE.md` seções 6/7/9 e
do pedido original da Fase 4: login (já coberto por `AUTH_API_CONTRACT.md`),
atualização (do jogo e do próprio Launcher), notícias, download de DLC,
verificação de integridade, verificação de versão. Roda embarcado no mesmo
processo do bot (`api/main.py: create_app`).

Todas as rotas abaixo são **novas** nesta fase, complementando `/auth` (Fase 2)
e reutilizando integralmente `Product`/`License`/`Player` (Fase 3) — nenhum
sistema paralelo de posse foi criado.

---

## 1. Regras não negociáveis (do pedido original)

1. **Nunca link permanente.** Toda URL de arquivo é assinada
   (`StorageProvider.generate_download_url`) com expiração curta
   (`STORAGE_DOWNLOAD_TTL_SECONDS`, default 600s / 10 min).
2. **O processo do bot nunca serve bytes.** Ele só autentica, checa posse e
   assina a URL — o download em si vai direto Launcher → storage.
3. **Compatível com Cloudflare R2, Amazon S3 e Backblaze B2** sem mudança de
   código: os 3 falam a mesma API S3 (SigV4). `providers/storage/
   s3_compatible.py: S3CompatibleStorageProvider` é a única implementação —
   trocar de provedor é só trocar `STORAGE_ENDPOINT_URL`/credenciais no `.env`.
4. **Todo download usa Manifest + SHA-256 + Versão + Checksum**: o manifest
   (`GameManifestEntry`) carrega `version`/`sha256`/`size_bytes` publicados
   por staff; `POST /download` devolve esses 3 campos junto da URL; `POST
   /download/{id}/complete` fecha o ciclo comparando o SHA-256 que o Launcher
   calculou localmente contra o do manifest.

---

## 2. Decisão de design: quando License é exigida

| Rota | Auth | Exige `License` ACTIVE |
|---|---|---|
| `GET /launcher/news` | não | não — conteúdo público |
| `GET /launcher/version` | não | não — o Launcher precisa checar sua própria versão antes de logar |
| `POST /update` | não | não — mesmo motivo; binário do Launcher não é um `Product` vendável |
| `GET /launcher/manifest` | sim | **sim** |
| `GET /player/licenses` | sim | — (mostra o inventário, não exige nada) |
| `GET /player/products` | sim | — (mostra catálogo + posse, não exige nada) |
| `POST /download` | sim | **sim** (reconfirmado, não reaproveita a checagem do manifest) |
| `POST /download/{id}/complete` | sim | — (só valida que o download é do próprio player) |

Não há exceção especial para Base Game: ele é só mais uma linha em `Product`
(`product_type=PERMANENT`) e precisa de uma `License` ACTIVE como qualquer
DLC/skin/pacote de assinatura — `LicenseService.grant_or_renew` já suporta
concessão manual por staff (`granted_by_staff_id`) para conceder Base Game de
graça a todo mundo, sem precisar de caso especial no código de autorização.
Isso era um ponto em aberto na seção 9 do documento de arquitetura ("Base
game... não depende de License" refere-se só ao modo offline, seção 8 —
resolvido aqui: a emissão da licença que viabiliza esse modo offline é sempre
staff-driven/automática de compra, nunca "sem License").

---

## 3. `GET /launcher/news`

Sem auth. Lista notícias publicadas (`is_published=True`, não deletadas),
mais recente primeiro.

Query: `limit` (opcional, 1–100, default 20).

Response `200`:
```json
[
  {
    "id": "uuid",
    "title": "Atualização 1.2",
    "content": "...",
    "cover_image_url": "https://.../capa.png",
    "published_at": "2026-08-06T12:00:00+00:00"
  }
]
```

---

## 4. `GET /launcher/version`

Sem auth. Versão atual do **próprio binário do Launcher** por plataforma
(`LauncherVersion`, distinto do manifest de conteúdo — ver seção 6 do
documento de arquitetura, decisão de detalhe resolvida como endpoint
dedicado).

Query: `platform` (`windows` | `macos` | `linux`, obrigatório).

Response `200`:
```json
{
  "platform": "windows",
  "version": "1.2.0",
  "sha256": "64 hex chars",
  "size_bytes": 52428800,
  "is_mandatory": true,
  "release_notes": "..."
}
```
`404 version_not_found` se nenhuma versão foi publicada pra essa plataforma.
O Launcher compara `version` com a versão local instalada; se diferente (ou
`is_mandatory=true`), chama `POST /update` pra obter a URL de download.

---

## 5. `GET /launcher/manifest`

Requer `Authorization: Bearer <access_token>` **e** `License` ACTIVE no
`product_id` pedido (`403 license_required` se não tiver). Retorna a versão
atual publicada de um `Product` (base game/DLC/etc) pro Launcher decidir se
precisa atualizar o conteúdo já instalado.

Query: `product_id` (uuid, obrigatório), `entry_type` (`full` | `patch`,
default `full`).

Response `200`:
```json
{
  "product_id": "uuid",
  "entry_type": "full",
  "version": "1.0.0",
  "sha256": "64 hex chars",
  "size_bytes": 4294967296,
  "depends_on": [],
  "release_notes": "..."
}
```
`404 manifest_not_found` se não há versão publicada pra esse produto/tipo.

Fluxo de update/reparo do Launcher (seção 7 do documento de arquitetura):
compara `version`/`sha256` locais contra a resposta — igual = "Jogar"
habilitado; versão diferente = baixa `FULL`/`PATCH`; mesma versão mas hash
local divergente = reparo (rebaixa só os arquivos corrompidos). Toda essa
lógica de comparação roda no cliente — o backend só informa o estado atual.

---

## 6. `GET /player/licenses`

Requer auth. Inventário completo do player — inclui `REVOKED`/`EXPIRED`
(histórico), não só `ACTIVE`. Base da tela "Biblioteca"/histórico de compras.

Response `200`:
```json
[
  {
    "id": "uuid",
    "product_id": "uuid",
    "product_slug": "patrono",
    "product_name": "Patrono",
    "status": "active",
    "purchase_source": "subscription:Patrono",
    "activated_at": "2026-08-01T10:00:00+00:00",
    "expires_at": "2026-09-01T10:00:00+00:00",
    "auto_renew": true,
    "revoked_at": null,
    "revoked_reason": null
  }
]
```

---

## 7. `GET /player/products`

Requer auth. Catálogo ativo (`Product.is_active=True`, não deletado) anotado
com posse do player — base da tela "Loja" (mostra o que falta comprar) e
"Biblioteca" (filtra `owned=true` no cliente).

Response `200`:
```json
[
  {
    "id": "uuid",
    "slug": "base-game",
    "name": "Base Game",
    "product_type": "permanent",
    "description": "...",
    "price_amount": 0,
    "currency": "BRL",
    "owned": true,
    "license_status": "active"
  }
]
```
`owned=true` exige `license_status == "active"` — uma licença `revoked`/
`expired` para esse produto aparece com `owned=false` (o player ainda vê que
já teve, mas o Launcher não libera o conteúdo).

---

## 8. `POST /download`

Requer auth. Autoriza o download de um arquivo de `Product` (base
game/DLC/skin/wallpaper/soundtrack/etc). Reconfirma `License` ACTIVE aqui —
nunca reaproveita a checagem de `/launcher/manifest`, pra minimizar a janela
entre "podia" e "ainda pode" (mesma regra do documento de arquitetura, seção
6).

Request:
```json
{"product_id": "uuid", "entry_type": "full", "device_uuid": "uuid"}
```
`device_uuid` é opcional — só usado pra auditoria (`Download.device_id`).

Response `200`:
```json
{
  "download_id": "uuid",
  "url": "https://<bucket>.<endpoint>/products/.../1.0.0.pkg?X-Amz-...",
  "version": "1.0.0",
  "sha256": "64 hex chars",
  "size_bytes": 4294967296,
  "entry_type": "full",
  "expires_at": "2026-08-06T15:40:00+00:00"
}
```
Erros: `403 license_required`, `404 manifest_not_found`,
`503 storage_not_configured` (backend sem `STORAGE_*` configurado),
`502 storage_error` (provedor recusou assinar).

Cada chamada cria uma linha em `Download` (status `AUTHORIZED`) — trilha de
auditoria que prova que a `License` estava ativa no momento exato da
autorização, mesmo que seja revogada depois.

---

## 9. `POST /download/{download_id}/complete`

Requer auth (só o dono do download pode reportar). Fecha o ciclo de
**verificação de integridade**: o Launcher calcula o SHA-256 do arquivo já
baixado e reporta aqui; o backend compara contra o `sha256` do manifest que
autorizou aquele download específico.

Request:
```json
{"client_sha256": "64 hex chars", "bytes_transferred": 4294967296}
```

Response `200`:
```json
{"download_id": "uuid", "status": "completed", "failure_reason": null}
```
Se o hash não bater: `{"status": "failed", "failure_reason": "checksum_mismatch"}`
— o Launcher deve re-tentar (dá suporte nativo a resumable/repair no cliente,
sem precisar re-autorizar do zero: um novo `POST /download` gera uma nova
linha). Idempotente: reportar duas vezes o mesmo `download_id` não sobrescreve
o veredito já registrado. `404 download_not_found` se o download não existe
ou pertence a outro player.

---

## 10. `POST /update`

Sem auth — o Launcher precisa se auto-atualizar antes de o usuário logar.
Não gera linha em `Download` (o binário do Launcher não é um `Product`, o
schema de `Download` exige `product_id`).

Request:
```json
{"platform": "windows"}
```

Response `200`:
```json
{
  "url": "https://.../launcher/windows/1.2.0.pkg?X-Amz-...",
  "version": "1.2.0",
  "sha256": "64 hex chars",
  "size_bytes": 52428800,
  "is_mandatory": true,
  "release_notes": "...",
  "expires_at": "2026-08-06T15:40:00+00:00"
}
```
`404 version_not_found`, `503 storage_not_configured`, `502 storage_error`.

---

## 11. Storage — configuração (`config/settings.py`)

| Env var | Obrigatória | Efeito |
|---|---|---|
| `STORAGE_PROVIDER` | não (default `r2`) | só rótulo de log/auditoria |
| `STORAGE_BUCKET` | sim, pra `/download`/`/update` funcionarem | bucket S3-compatível |
| `STORAGE_ENDPOINT_URL` | não (vazio = AWS S3 real) | R2: `https://<account_id>.r2.cloudflarestorage.com`; B2: `https://s3.<region>.backblazeb2.com` |
| `STORAGE_REGION` | não (default `auto`) | região SigV4 |
| `STORAGE_ACCESS_KEY_ID` / `STORAGE_SECRET_ACCESS_KEY` | sim | credenciais |
| `STORAGE_DOWNLOAD_TTL_SECONDS` | não (default 600) | duração da URL assinada |

Sem `STORAGE_BUCKET`/`STORAGE_ACCESS_KEY_ID`/`STORAGE_SECRET_ACCESS_KEY`
configurados, o backend sobe normalmente (todas as outras rotas funcionam) mas
`/download` e `/update` respondem `503 storage_not_configured` — ver
`api/main.py: _build_storage_provider`.

---

## 12. Testes

- `bot/tests/test_download_service.py` + `bot/tests/_fakes_download.py` —
  cobre: license obrigatória, manifest ausente, URL assinada + linha de
  auditoria, erro de storage, storage não configurado, checksum batendo/não
  batendo, idempotência do `complete`, isolamento entre players, update do
  Launcher (com/sem versão publicada).
- `bot/tests/test_launcher_content_service.py` +
  `bot/tests/_fakes_launcher_content.py` — cobre news/version/manifest.
- Mesmo padrão de fakes em memória de `tests/_fakes_auth.py` (models usam
  tipos Postgres-only, não rodam contra SQLite). Rotas em si (FastAPI) não
  ganharam teste de integração HTTP nesta fase — mesmo padrão já aceito em
  `auth_routes.py`, cujo contrato é validado via `test_auth_routes.py`
  chamando o `AuthService` por trás; aqui a cobertura equivalente está nos
  testes de serviço acima, que exercitam exatamente a lógica que as rotas só
  repassam (mapeamento de `DownloadError.code` → HTTP status é tabela pura,
  sem lógica condicional a testar).
