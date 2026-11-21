"""Local checkpoints and bounded, read-only HTTP for source search helpers."""

from __future__ import annotations

import hashlib
import http.cookiejar
import json
import os
import re
import socket
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def configure_utf8_stdio():
    """Keep CLI output readable when an agent captures a legacy-encoded pipe."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


class SourceError(Exception):
    """A source or checkpoint could not be read reliably."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def timestamp():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def fingerprint(value):
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def read_json(path):
    with Path(path).expanduser().open(encoding="utf-8-sig") as handle:
        return json.load(handle)


def atomic_bytes(path, content):
    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def save_json(path, value):
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def output_json(value, path=None):
    if path:
        save_json(path, value)
    else:
        print(json.dumps(value, ensure_ascii=False, indent=2))


def outside_skill(path):
    path = Path(path).expanduser().resolve()
    root = Path(__file__).resolve().parent.parent
    if path == root or root in path.parents:
        raise SourceError("Храните результаты исследования вне папки навыка.")
    return path


@contextmanager
def state_lock(path):
    """Exclude concurrent writers. Stale locks need an explicit local check."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise SourceError(f"Состояние занято: {path}. Проверьте процесс перед удалением lock-файла.") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        yield
    finally:
        path.unlink(missing_ok=True)


class SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        old = urllib.parse.urlsplit(request.full_url)
        new = urllib.parse.urlsplit(new_url)
        if (old.scheme, old.netloc) != (new.scheme, new.netloc):
            raise SourceError("Источник перенаправляет на другой адрес; проверьте вход в браузере.", code)
        if code in (301, 302, 303) and request.get_method() == "POST":
            raise SourceError("Источник перенаправляет запрос; проверьте формат API и доступ.", code)
        return super().redirect_request(request, response, code, message, headers, new_url)


class SourceClient:
    """Requests stay on one source. No retries for access denial or rate limits."""

    def __init__(self, base, context=None, interval=0.4, referer=None):
        self.base = base.rstrip("/")
        self.referer = referer or self.base + "/"
        self.interval = interval
        self.last_request = 0.0
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            SameOriginRedirect(), urllib.request.HTTPCookieProcessor(self.cookies),
            urllib.request.HTTPSHandler(context=context or ssl.create_default_context()),
        )

    def request(self, path, body=None, as_json=True):
        url = self.base + path
        # The only POSTs in these helpers are source searches, never tree mutations.
        data = None if body is None else json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {
            "User-Agent": "ex-ussr-kinship-research/1.6 (source research)",
            "Accept": "application/json" if as_json else "text/html",
        }
        if body is not None:
            headers.update({"Content-Type": "application/json", "Referer": self.referer, "Origin": self.base})
        for attempt in range(3):
            time.sleep(max(0, self.interval - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            request = urllib.request.Request(url, data=data, headers=headers)
            try:
                with self.opener.open(request, timeout=45) as response:
                    content = response.read().decode("utf-8")
                if re.search(r'<(?:iframe|div|form)[^>]*(?:smartcaptcha|g-recaptcha|captcha-container)', content, re.IGNORECASE):
                    raise SourceError("Источник показывает CAPTCHA; проверку проходит пользователь.", 403)
                if not as_json:
                    return content
                if content.lstrip().startswith("<"):
                    raise SourceError("Вместо данных получена веб-страница; проверьте вход или CAPTCHA в браузере.", 403)
                try:
                    return json.loads(content)
                except json.JSONDecodeError as exc:
                    raise SourceError("Источник вернул не JSON: возможен вход, CAPTCHA или изменение API.") from exc
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403, 429):
                    raise SourceError(f"HTTP {exc.code}: запросы остановлены; проверьте доступ или лимит.", exc.code) from exc
                if exc.code not in (500, 502, 503, 504) or attempt == 2:
                    raise SourceError(f"HTTP {exc.code}: источник недоступен.", exc.code) from exc
                retry_after = exc.headers.get("Retry-After")
                if retry_after:
                    raise SourceError("Источник просит повторить запрос позже; состояние сохранено.", exc.code) from exc
            except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
                if attempt == 2:
                    raise SourceError("Сетевая ошибка или ошибка TLS; проверьте доступ к источнику.") from exc
            time.sleep(2 ** attempt)
        raise SourceError("Источник недоступен.")
