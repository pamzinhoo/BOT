from __future__ import annotations

from core.logger import get_logger
from providers.storage.base import StorageError, StorageProvider

logger = get_logger("storage_s3_compatible")


class S3CompatibleStorageProvider(StorageProvider):
    """Cliente unico compativel com Cloudflare R2, Amazon S3 e Backblaze B2 —
    os 3 implementam a API S3 (SigV4). Presign e computacao local (HMAC), sem
    chamada de rede, entao gerar a URL nao bloqueia o event loop.

    `name` (r2/s3/b2) e so informativo (logging/auditoria) — o comportamento e
    identico independente do provedor, controlado inteiramente por
    `endpoint_url` (None = AWS S3 real; URL do R2/B2 pros outros dois)."""

    def __init__(
        self,
        *,
        name: str,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
        endpoint_url: str | None = None,
        region_name: str = "auto",
    ) -> None:
        if not bucket or not access_key_id or not secret_access_key:
            raise StorageError(
                "Storage nao configurado — defina bucket/access_key_id/secret_access_key (env)."
            )
        import boto3
        from botocore.config import Config

        self.name = name
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region_name,
            config=Config(signature_version="s3v4"),
        )

    def generate_download_url(
        self, storage_path: str, *, expires_in_seconds: int, filename: str | None = None
    ) -> str:
        params: dict[str, str] = {"Bucket": self._bucket, "Key": storage_path}
        if filename:
            params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
        try:
            return self._client.generate_presigned_url(
                "get_object", Params=params, ExpiresIn=expires_in_seconds
            )
        except Exception as exc:
            logger.exception("Falha ao gerar URL assinada (%s) para %s.", self.name, storage_path)
            raise StorageError(f"Falha ao gerar URL de download ({self.name}).") from exc
