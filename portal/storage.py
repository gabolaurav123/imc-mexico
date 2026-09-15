"""Private media storage. Only permission-checked application views serve files."""
import mimetypes
import os
import tempfile
from pathlib import PurePosixPath

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.core.files import File
from django.core.files.storage import FileSystemStorage, Storage
from django.utils.deconstruct import deconstructible


def option(name, default=None):
    return getattr(settings, name, os.environ.get(name, default))


@deconstructible
class PrivateStorage(Storage):
    """S3-compatible private bucket, or a persistent local directory.

    Deliberately has no public URL or presigning method. S3 bucket-level public
    access blocking is a deployment requirement; no public ACL is ever written.
    """

    @property
    def bucket(self):
        return option("PRIVATE_S3_BUCKET", "")

    @property
    def local(self):
        return FileSystemStorage(location=settings.MEDIA_ROOT, base_url=None,
                                 file_permissions_mode=0o600, directory_permissions_mode=0o700)

    def client(self):
        import boto3
        from botocore.config import Config
        return boto3.client(
            "s3", endpoint_url=option("PRIVATE_S3_ENDPOINT_URL") or None,
            region_name=option("PRIVATE_S3_REGION", "us-east-1") or "us-east-1",
            aws_access_key_id=option("PRIVATE_S3_ACCESS_KEY_ID") or None,
            aws_secret_access_key=option("PRIVATE_S3_SECRET_ACCESS_KEY") or None,
            config=Config(connect_timeout=10, read_timeout=60,
                          retries={"max_attempts": 3, "mode": "standard"}),
        )

    @staticmethod
    def safe_name(name):
        name = str(name).replace("\\", "/")
        if not name or name.startswith("/") or ".." in PurePosixPath(name).parts or ":" in name:
            raise SuspiciousFileOperation("Nombre de archivo no válido.")
        return name

    def _open(self, name, mode="rb"):
        name = self.safe_name(name)
        if mode != "rb":
            raise ValueError("Los archivos privados solo se abren para lectura binaria.")
        if not self.bucket:
            return self.local.open(name, mode)
        stream = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
        try:
            self.client().download_fileobj(self.bucket, name, stream)
            stream.seek(0)
            return File(stream, name=name)
        except Exception:
            stream.close()
            raise

    def _save(self, name, content):
        name = self.safe_name(name)
        if not self.bucket:
            return self.local.save(name, content)
        content.seek(0)
        self.client().upload_fileobj(content, self.bucket, name, ExtraArgs={
            "ContentType": mimetypes.guess_type(name)[0] or "application/octet-stream",
            "CacheControl": "private, no-store",
        })
        return name

    def exists(self, name):
        name = self.safe_name(name)
        if not self.bucket:
            return self.local.exists(name)
        from botocore.exceptions import ClientError
        try:
            self.client().head_object(Bucket=self.bucket, Key=name)
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise

    def delete(self, name):
        if not name:
            return
        name = self.safe_name(name)
        if not self.bucket:
            self.local.delete(name)
        else:
            self.client().delete_object(Bucket=self.bucket, Key=name)

    def size(self, name):
        name = self.safe_name(name)
        if not self.bucket:
            return self.local.size(name)
        return self.client().head_object(Bucket=self.bucket, Key=name)["ContentLength"]

    def url(self, name):
        raise ValueError("Los archivos privados requieren una vista con permisos.")

    def path(self, name):
        if self.bucket:
            raise NotImplementedError("El almacenamiento S3 no dispone de rutas locales.")
        return self.local.path(self.safe_name(name))
