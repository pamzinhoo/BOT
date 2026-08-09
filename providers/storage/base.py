from __future__ import annotations

from abc import ABC, abstractmethod


class StorageError(RuntimeError):
    """Erro de comunicacao com o provedor de armazenamento (rede, credenciais,
    bucket inexistente). Nunca deve carregar credenciais na mensagem."""


class StorageProvider(ABC):
    """Camada de abstracao sobre o backend de objetos que guarda os arquivos
    de DLC/base game/binario do Launcher. O processo do bot NUNCA serve bytes
    — so assina URLs de curta duracao pro cliente baixar direto do storage.

    Cloudflare R2, Amazon S3 e Backblaze B2 falam a mesma API S3 (SigV4), entao
    uma unica implementacao (S3CompatibleStorageProvider) cobre os 3 — trocar
    de provedor e so trocar endpoint/credenciais via env, nunca codigo."""

    name: str

    @abstractmethod
    def generate_download_url(
        self, storage_path: str, *, expires_in_seconds: int, filename: str | None = None
    ) -> str:
        """Gera uma URL de download temporaria (GET) pra `storage_path`. Nunca
        retorna um link permanente — `expires_in_seconds` sempre curto
        (minutos, nao horas/dias)."""
        ...
