#!/usr/bin/env python3
"""Search names in saved FamilySearch evidence fragments."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # `python -I` omits the script folder

from familysearch_browser import browser_import
from research_common import configure_utf8_stdio, SourceError, outside_skill, output_json, read_json


def compile_patterns(config=None, surnames=(), beacons=()):
    config = config or {}
    if not isinstance(config, dict) or set(config) - {"_comment", "surnames", "beacons"}:
        raise SourceError("Неизвестные поля конфигурации поиска.")
    definitions = []
    for layer, extra in (("surnames", surnames), ("beacons", beacons)):
        values = config.get(layer, {})
        if not isinstance(values, dict):
            raise SourceError(f"{layer}: ожидается объект метка → выражение.")
        definitions.extend((layer, label, pattern) for label, pattern in values.items())
        definitions.extend((layer, pattern, pattern) for pattern in extra)
    result, labels = [], set()
    for layer, label, pattern in definitions:
        if not isinstance(label, str) or not label.strip() or label in labels or not isinstance(pattern, str) or not pattern:
            raise SourceError("Пустая/повторная метка или некорректное выражение.")
        labels.add(label)
        try:
            result.append((layer, label, re.compile(pattern, re.IGNORECASE)))
        except re.error as exc:
            raise SourceError(f"Некорректное Python regex для метки {label}.") from exc
    return result


def parser():
    root = argparse.ArgumentParser(allow_abbrev=False, description="FamilySearch: локальный поиск по именам и тексту сохранённых фрагментов индекса.")
    commands = root.add_subparsers(dest="command", required=True)
    browser = commands.add_parser("browser-import", allow_abbrev=False, help="Разобрать сохранённые точечные фрагменты индекса")
    browser.add_argument("files", nargs="+")
    browser.add_argument("--surnames", nargs="+", default=[])
    browser.add_argument("--beacons", nargs="+", default=[])
    browser.add_argument("--config")
    browser.add_argument("--out", help="JSON вне папки навыка; по умолчанию stdout")
    return root


def run(args):
    if args.out:
        outside_skill(args.out)
    config = read_json(args.config) if args.config else {}
    patterns = compile_patterns(config, args.surnames, args.beacons)
    result = browser_import(args.files, patterns)
    output_json(result, args.out)
    return 0


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        return run(args)
    except (SourceError, OSError, ValueError, TypeError, KeyError) as exc:
        message = str(exc) if isinstance(exc, SourceError) else "Некорректный входной файл или ошибка локального чтения/записи."
        print("Ошибка: " + message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    configure_utf8_stdio()
    raise SystemExit(main())
