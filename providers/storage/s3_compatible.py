from __future__ import annotations

from core.logger import get_logger
from providers.storage.base import StorageError, StorageProvider

logger = get_logger("storage_s3_compatible")


class S3CompatibleStorageProvider(StorageProvider):
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

    def upload_bytes(self, storage_path: str, data: bytes, *, content_type: str) -> None:
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=storage_path,
                Body=data,
                ContentType=content_type,
            )
        except Exception as exc:
            logger.exception("Falha ao enviar objeto (%s) para %s.", self.name, storage_path)
            raise StorageError(f"Falha ao enviar arquivo ({self.name}).") from exc

    def download_bytes(self, storage_path: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=storage_path)
            return response["Body"].read()
        except Exception as exc:
            logger.exception("Falha ao baixar objeto (%s) de %s.", self.name, storage_path)
            raise StorageError(f"Falha ao baixar arquivo ({self.name}).") from exc

    def delete_object(self, storage_path: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=storage_path)
        except Exception as exc:
            logger.exception("Falha ao remover objeto (%s) de %s.", self.name, storage_path)
            raise StorageError(f"Falha ao apagar arquivo ({self.name}).") from exc
