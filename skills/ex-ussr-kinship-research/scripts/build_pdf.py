#!/usr/bin/env python3
"""Build the human-readable PDF report from an HTML file via headless Chrome/Chromium."""

from __future__ import annotations

import argparse
import html
import html.parser
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

PLACEHOLDER_RE = re.compile(r"<[^<>\n]+>")

CHROME_NAMES = [
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "chrome",
    "msedge",
    "microsoft-edge",
]
CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]

STATIC_TAGS = set(
    "html head body title meta style a abbr address area article aside b bdi bdo "
    "blockquote br caption cite code col colgroup data dd del details dfn div dl dt "
    "em figcaption figure footer h1 h2 h3 h4 h5 h6 header hgroup hr i img ins kbd "
    "li main map mark menu nav ol p pre q rp rt ruby s samp section small span "
    "strong sub summary sup table tbody td th thead time tr u ul var wbr".split()
)
ACTIVE_TAGS = {
    "script", "iframe", "frame", "frameset", "object", "embed", "applet",
    "portal", "fencedframe", "form", "input", "button", "select", "textarea",
    "base", "link",
}
PRINT_CSP = (
    "default-src 'none'; script-src 'none'; connect-src 'none'; "
    "frame-src 'none'; object-src 'none'; media-src 'none'; "
    "img-src file: data:; font-src file: data:; style-src 'unsafe-inline'; "
    "base-uri file:; form-action 'none'"
)


class VisibleText(html.parser.HTMLParser):
    """Collect text and images, rejecting active HTML and unknown placeholder tags."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.chunks: list[str] = []
        self.images: list[str] = []
        self.problems: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ACTIVE_TAGS:
            self.problems.append(f"активный или внешний HTML запрещён: <{tag}>")
        elif tag not in STATIC_TAGS:
            self.problems.append(
                "незаполненный плейсхолдер или неподдерживаемый тег: "
                + (self.get_starttag_text() or f"<{tag}>")
            )
        attributes = dict(attrs)
        if tag == "meta" and (attributes.get("http-equiv") or "").strip().lower() == "refresh":
            self.problems.append("автоматический переход meta refresh запрещён")
        for key, value in attrs:
            if key.startswith("on") or key in {"srcdoc", "ping", "action", "formaction", "srcset"}:
                self.problems.append(f"активный или неподдерживаемый атрибут запрещён: {key}")
            if value and PLACEHOLDER_RE.search(value):
                self.problems.append(f"незаполненный плейсхолдер в атрибуте {key}: {value}")
            if key == "href" and tag in {"a", "area"} and value:
                try:
                    target = urlsplit(re.sub(r"[\x00-\x20\x7f]", "", value))
                except ValueError:
                    self.problems.append(f"некорректная ссылка: {value}")
                    continue
                if target.scheme.lower() not in {"", "http", "https", "mailto", "file"}:
                    self.problems.append(f"небезопасная схема ссылки: {value}")
                elif (not target.scheme or target.scheme == "file") and target.netloc not in {"", "localhost"}:
                    self.problems.append(f"сетевая файловая ссылка запрещена: {value}")
        if tag in ("style", "script", "title"):
            self.skip += 1
        if tag == "img":
            src = dict(attrs).get("src") or ""
            self.images.append(src)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("style", "script", "title") and self.skip:
            self.skip -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.chunks.append(data)

    def unknown_decl(self, data: str) -> None:  # pragma: no cover - defensive
        pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Собирает читаемую PDF-версию отчёта из HTML (SKILL.md, шаг 12)."
    )
    parser.add_argument("--html", required=True, help="HTML-файл отчёта (обычно <дело>/report.html)")
    parser.add_argument("--out", help="Путь к PDF; по умолчанию рядом с HTML")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Только проверить текст и изображения, PDF не собирать",
    )
    # Accepted for older invocations; presentation choices no longer block printing.
    parser.add_argument("--allow-service-ids", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--chrome", help="Путь к Chrome/Chromium/Edge; иначе переменная CHROME_PATH или автопоиск")
    parser.add_argument(
        "--png-dir",
        help="Отрисовать страницы PDF в PNG для визуальной проверки (нужен установленный pypdfium2)",
    )
    return parser.parse_args()


def inspect_html(source: str, html_path: Path) -> tuple[list[str], list[str]]:
    parser = VisibleText()
    parser.feed(source)
    parser.close()
    text = re.sub(r"\s+", " ", "".join(parser.chunks))

    problems = parser.problems[:]
    placeholders = sorted(set(PLACEHOLDER_RE.findall(text)))
    if placeholders:
        problems.append("незаполненный плейсхолдер <…>: " + ", ".join(placeholders[:10]))

    missing: list[str] = []
    for src in parser.images:
        if not src or "<" in src:
            missing.append(src or "<пустой src>")
            continue
        try:
            target = urlsplit(src)
        except ValueError:
            problems.append(f"некорректный путь изображения: {src}")
            continue
        if target.scheme.lower() == "data" and src.lower().startswith("data:image/"):
            continue
        if target.scheme.lower() not in {"", "file"} or target.netloc not in {"", "localhost"}:
            problems.append(f"изображение должно быть локальным или data:image: {src}")
            continue
        image_path = Path(url2pathname(target.path)) if target.scheme else Path(unquote(target.path))
        if not (html_path.parent / image_path).is_file():
            missing.append(src)
    return problems, missing


def check_html(html_path: Path) -> tuple[list[str], list[str]]:
    return inspect_html(html_path.read_text(encoding="utf-8"), html_path)


def find_chrome(explicit: str | None) -> str | None:
    for candidate in (explicit, os.environ.get("CHROME_PATH")):
        if candidate and Path(candidate).exists():
            return candidate
    for name in CHROME_NAMES:
        found = shutil.which(name)
        if found:
            return found
    for path in CHROME_PATHS:
        if Path(path).exists():
            return path
    return None


def print_pdf(chrome: str, html_path: Path, out_path: Path) -> int:
    html_path, out_path = html_path.resolve(), out_path.resolve()
    if html_path == out_path or (out_path.exists() and html_path.samefile(out_path)):
        print("Ошибка: исходный HTML и выходной PDF должны быть разными файлами.", file=sys.stderr)
        return 2
    source = html_path.read_text(encoding="utf-8")
    problems, missing = inspect_html(source, html_path)
    if problems or missing:
        print("Ошибка: HTML не прошёл проверку перед печатью: " + "; ".join(problems + missing), file=sys.stderr)
        return 1
    # The first policy is enforced before any report content is parsed. A trusted
    # local base preserves relative image paths while the temporary copy is printed.
    printable = (
        '<!doctype html>\n<meta charset="utf-8">\n'
        f'<meta http-equiv="Content-Security-Policy" content="{html.escape(PRINT_CSP, quote=True)}">\n'
        f'<base href="{html.escape(html_path.parent.as_uri() + "/", quote=True)}">\n'
        + source
    )
    diagnostics = ""
    with tempfile.TemporaryDirectory(prefix=".kinship-pdf-", dir=out_path.parent) as staging:
        stage = Path(staging)
        staged_html, staged_pdf = stage / "report.html", stage / "report.pdf"
        staged_html.write_text(printable, encoding="utf-8")
        base = [
            chrome,
            "--disable-gpu",
            "--disable-background-networking",
            "--disable-extensions",
            "--disable-sync",
            "--host-resolver-rules=MAP * ~NOTFOUND",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={stage / 'profile'}",
            "--no-pdf-header-footer",
            f"--print-to-pdf={staged_pdf}",
            staged_html.as_uri(),
        ]
        for headless in ("--headless=new", "--headless"):
            staged_pdf.unlink(missing_ok=True)
            try:
                result = subprocess.run(
                    [base[0], headless, *base[1:]],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=180,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                diagnostics = str(exc)
                continue
            diagnostics = result.stderr.decode("utf-8", "replace")[-2000:]
            if result.returncode == 0 and staged_pdf.is_file():
                data = staged_pdf.read_bytes()
                if data.startswith(b"%PDF-") and data.rstrip().endswith(b"%%EOF") and count_pages(staged_pdf):
                    # Staging is on the destination filesystem: a failed render
                    # never removes or truncates an existing report.
                    staged_pdf.replace(out_path)
                    return 0
        sys.stderr.write(diagnostics)
    return 3


def count_pages(pdf_path: Path) -> int:
    return len(re.findall(rb"/Type\s*/Page\b", pdf_path.read_bytes()))


def render_png(pdf_path: Path, png_dir: Path) -> None:
    try:
        import pypdfium2 as pdfium  # type: ignore
    except ImportError:
        print(
            "pypdfium2 не установлен: страницы не отрисованы. Просмотрите PDF другим способом "
            "(встроенный просмотр PDF агента, pdftoppm, системный просмотрщик)."
        )
        return
    png_dir.mkdir(parents=True, exist_ok=True)
    pdf = pdfium.PdfDocument(str(pdf_path))
    for index in range(len(pdf)):
        pdf[index].render(scale=1.3).to_pil().save(png_dir / f"page{index + 1}.png")
    print(f"Страницы отрисованы: {png_dir} ({len(pdf)} шт.)")


def main() -> int:
    args = parse_args()
    html_path = Path(args.html).expanduser().resolve()
    if not html_path.is_file():
        print(f"Ошибка: нет файла {html_path}", file=sys.stderr)
        return 2

    problems, missing = check_html(html_path)
    if missing:
        print("Ошибка: не найдены изображения: " + ", ".join(missing), file=sys.stderr)
    if problems:
        print("HTML не прошёл проверку:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
    if missing or problems:
        return 1
    if args.check_only:
        print("Проверка пройдена.")
        return 0

    chrome = find_chrome(args.chrome)
    if not chrome:
        print(
            "Ошибка: не найден Chrome, Chromium или Edge. Укажите путь через --chrome или CHROME_PATH.",
            file=sys.stderr,
        )
        return 2

    out_path = Path(args.out).expanduser().resolve() if args.out else html_path.with_suffix(".pdf")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    code = print_pdf(chrome, html_path, out_path)
    if code:
        print("Ошибка: браузер не смог напечатать PDF.", file=sys.stderr)
        return code

    print(f"PDF собран: {out_path} (страниц: {count_pages(out_path)}, {out_path.stat().st_size // 1024} КБ)")
    if args.png_dir:
        render_png(out_path, Path(args.png_dir).expanduser().resolve())
    print("Просмотрите каждую страницу перед отправкой пользователю (SKILL.md, шаг 12, п. 8).")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from research_common import configure_utf8_stdio

    configure_utf8_stdio()
    raise SystemExit(main())
