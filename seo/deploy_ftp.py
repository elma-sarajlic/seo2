from __future__ import annotations

import ftplib
import json
import os
import posixpath
import sys
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "seo" / "deploy-manifest.json"


def env(name: str, default: str = "") -> str:
    value = os.getenv(name, default).strip()
    if not value:
        raise RuntimeError(f"Missing required deployment value: {name}")
    return value


def safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise RuntimeError(f"Unsafe deploy path: {value}")
    return path


def ensure_directory(ftp: ftplib.FTP, directory: str) -> None:
    if not directory or directory == "/":
        return
    current = "/" if directory.startswith("/") else ""
    for part in PurePosixPath(directory).parts:
        if part in {"/", ".", ""}:
            continue
        current = posixpath.join(current, part)
        try:
            ftp.mkd(current)
        except ftplib.error_perm as error:
            if not str(error).startswith("550"):
                raise


def main() -> int:
    host = env("FTP_HOST")
    username = env("FTP_USERNAME")
    password = env("FTP_PASSWORD")
    remote_root = os.getenv("FTP_REMOTE_ROOT", "/public_html").strip() or "/public_html"
    port = int(os.getenv("FTP_PORT", "21"))
    use_tls = os.getenv("FTP_TLS", "true").strip().lower() in {"1", "true", "yes", "on"}
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    files = [safe_relative(value) for value in manifest.get("files", [])]
    if not files:
        raise RuntimeError("Deploy manifest contains no files")

    client: ftplib.FTP
    client = ftplib.FTP_TLS() if use_tls else ftplib.FTP()
    client.connect(host, port, timeout=30)
    client.login(username, password)
    if use_tls:
        assert isinstance(client, ftplib.FTP_TLS)
        client.prot_p()

    try:
        for relative in files:
            local_path = ROOT.joinpath(*relative.parts)
            if not local_path.is_file():
                raise RuntimeError(f"Deploy file is missing: {relative.as_posix()}")
            remote_path = posixpath.join(remote_root.rstrip("/"), relative.as_posix())
            ensure_directory(client, posixpath.dirname(remote_path))
            with local_path.open("rb") as handle:
                client.storbinary(f"STOR {remote_path}", handle)
            print(f"Uploaded {relative.as_posix()}")
    finally:
        try:
            client.quit()
        except Exception:
            client.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"cPanel deployment failed: {error}", file=sys.stderr)
        raise
