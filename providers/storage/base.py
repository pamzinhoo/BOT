from __future__ import annotations

from abc import ABC, abstractmethod


class StorageError(RuntimeError):
    """Erro de comunicacao com o provedor de armazenamento (rede, credenciais,
    bucket inexistente). Nunca deve carregar credenciais na mensagem."""


class StorageProvider(ABC):
    """Abstracao sobre o storage S3-compativel usado pelo bot."""

    name: str

    @abstractmethod
    def generate_download_url(
        self, storage_path: str, *, expires_in_seconds: int, filename: str | None = None
    ) -> str: ...

    @abstractmethod
    def upload_bytes(self, storage_path: str, data: bytes, *, content_type: str) -> None: ...

    @abstractmethod
    def download_bytes(self, storage_path: str) -> bytes: ...

    @abstractmethod
    def delete_object(self, storage_path: str) -> None: ...
