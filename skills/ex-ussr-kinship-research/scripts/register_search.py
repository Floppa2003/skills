#!/usr/bin/env python3
"""Register source-search leads (FamilySearch, GWAR, or any site via a manual JSON) in an existing case without asserting identities."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # `python -I` omits the script folder

from research_common import (configure_utf8_stdio, SourceError, atomic_bytes, fingerprint, outside_skill,
                             output_json, state_lock, timestamp)


def read_register(path, id_field):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames
        if not fields or id_field not in fields:
            raise SourceError(f"Некорректный реестр {path.name}.")
        rows = list(reader)
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise SourceError(f"Повреждена строка CSV: {path.name}.")
    ids = [row[id_field] for row in rows]
    if any(not value for value in ids) or len(set(ids)) != len(ids):
        raise SourceError(f"Пустые или повторные ID в {path.name}.")
    return fields, rows


def save_register(path, fields, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    atomic_bytes(path, stream.getvalue().encode("utf-8"))


def next_id(rows, field, prefix):
    numbers = [int(match.group(1)) for row in rows if (match := re.fullmatch(re.escape(prefix) + r"(\d+)", row[field]))]
    return f"{prefix}{max(numbers, default=0) + 1:04d}"


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def fs_items(data):
    candidates = data.get("candidates")
    if not isinstance(candidates, list):
        raise SourceError("Передайте результат локального анализа фрагментов FamilySearch.")
    for candidate in candidates:
        record, rid = candidate.get("record"), candidate.get("rid")
        if not rid or not isinstance(record, dict) or not isinstance(record.get("persons"), dict) or not record["persons"]:
            raise SourceError("Некорректный кандидат FamilySearch.")
        people = record["persons"]
        principal = next((pid for pid, person in people.items() if person.get("principal")), next(iter(people)))
        ark = people[principal].get("ark", "")
        if record.get("browser_url"):
            url = record["browser_url"]
        elif ark.startswith("https://www.familysearch.org/"):
            url = ark
        elif ark and not urllib.parse.urlsplit(ark).scheme:
            url = "https://www.familysearch.org/ark:/61903/1:1:" + urllib.parse.quote(ark, safe="")
        else:
            url = ""  # No public locator observed; retain the local source snapshot.
        locations = candidate.get("locations", [])
        reference = {"RID": rid if record.get("identifier_kind") != "local-browser-observation" else "",
                     "local_observation_id": rid if record.get("identifier_kind") == "local-browser-observation" else "",
                     "locations": locations}
        names = list(dict.fromkeys(name for person in people.values() for name in (person.get("names") or [person.get("name", "")]) if name))
        yield {"id": str(rid), "snapshot": record, "locations": locations,
               "captured_at": record.get("captured_at", ""), "source_title": "FamilySearch — индекс записи " + str(rid),
               "source_url_or_path": url, "repository_or_archive": "FamilySearch; архив оригинала уточнить",
               "archival_reference": encode(reference),
               "names_as_written": "; ".join(names),
               "summary": "Кандидат из текстового фрагмента индекса; личность и родство требуют проверки."}


# Report/hospital card routes reported by the contributor in PR #50 (2026-10-27);
# POW card route reported by the contributor in PR #64 (2026-10-28).
GWAR_CARD_PAGES = ("chelovek_donesenie", "chelovek_gospital", "chelovek_plen")


def gwar_items(data):
    if not isinstance(data.get("hits"), list):
        raise SourceError("Для GWAR передайте результат search или volost.")
    for hit in data["hits"]:
        if not isinstance(hit, dict) or not hit.get("_id") or not isinstance(hit.get("_source"), dict):
            raise SourceError("Некорректная карточка GWAR.")
        source = hit["_source"]
        identity = "|".join(str(hit.get(field, "")) for field in ("_index", "_type", "_id"))
        name = " ".join(str(source.get(field) or "") for field in ("last_name", "first_name", "middle_name")).strip()
        url = "https://gwar.mil.ru/heroes/"
        if hit.get("_type") in GWAR_CARD_PAGES and re.fullmatch(r"[0-9]+", str(hit["_id"])):
            url += f"{hit['_type']}{hit['_id']}/"
        yield {"id": identity, "snapshot": hit, "captured_at": data.get("captured_at", ""),
               "source_title": "GWAR — " + (name or str(hit["_id"])),
               "source_url_or_path": url, "repository_or_archive": "GWAR; архив оригинала уточнить",
               "archival_reference": encode({"card": identity, "documents_pages": source.get("documents_pages", {}),
                                              "military_unit_name": source.get("military_unit_name", "")}),
               "record_date": str(source.get("event_date_from") or ""),
               # Report cards usually leave birth_place empty and fill volost/uezd/gubernia.
               "place_as_written": ", ".join(str(source[field]) for field in (
                   "birth_place", "birth_place_volost", "birth_place_uezd", "birth_place_gubernia") if source.get(field)),
               "names_as_written": name,
               "summary": "Карточка Первой мировой; место и одноимённые лица требуют проверки по документу."}


MANUAL_TEXT_FIELDS = ("source_url_or_path", "repository_or_archive", "archival_reference", "record_date",
                      "place_as_written", "names_as_written", "language_script", "summary")
MANUAL_ITEM_KEYS = {"id", "source_title", "snapshot", *MANUAL_TEXT_FIELDS}


def manual_items(data):
    """Validate a hand-described search in any source and yield items shaped like fs_items/gwar_items."""
    domain, query = data.get("source_or_domain"), data.get("query")
    if not isinstance(domain, str) or not domain.strip():
        raise SourceError("Для manual укажите непустой source_or_domain.")
    if not (isinstance(query, dict) and query) and not (isinstance(query, str) and query.strip()):
        raise SourceError("Для manual укажите query: непустой объект или строку.")
    if "captured_at" in data and not isinstance(data["captured_at"], str):
        raise SourceError("captured_at должен быть строкой.")
    if not isinstance(data.get("items"), list):
        raise SourceError("Для manual items должен быть списком (пустым, если находок нет).")
    for number, item in enumerate(data["items"], 1):
        if not isinstance(item, dict):
            raise SourceError(f"manual: элемент {number} должен быть объектом.")
        unknown = sorted(set(item) - MANUAL_ITEM_KEYS)
        if unknown:
            raise SourceError(f"manual: элемент {number} содержит неизвестные поля: {', '.join(unknown)}.")
        for field in ("id", "source_title"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise SourceError(f"manual: у элемента {number} нужно непустое поле {field}.")
        for field in MANUAL_TEXT_FIELDS:
            if field in item and not isinstance(item[field], str):
                raise SourceError(f"manual: поле {field} элемента {number} должно быть строкой.")
        if "snapshot" in item and not isinstance(item["snapshot"], dict):
            raise SourceError(f"manual: поле snapshot элемента {number} должно быть объектом.")
        yield {"id": item["id"], "snapshot": {"source_or_domain": domain.strip(), **item}, "captured_at": data.get("captured_at", ""),
               "source_title": item["source_title"],
               **{field: item.get(field, "") for field in MANUAL_TEXT_FIELDS if field not in ("repository_or_archive", "summary")},
               "repository_or_archive": item.get("repository_or_archive") or "уточнить по источнику",
               "summary": item.get("summary") or "Наводка из ручного поиска; личность и родство требуют проверки."}


def without_capture(value):
    if isinstance(value, dict):
        return {key: without_capture(item) for key, item in value.items() if key != "captured_at"}
    if isinstance(value, list):
        return [without_capture(item) for item in value]
    return value


def snapshot_key(source, identity, snapshot):
    snapshot = without_capture(snapshot)
    if source == "gwar" and isinstance(snapshot, dict):
        # Search ranking varies between name and locality queries of the same card.
        snapshot = {key: value for key, value in snapshot.items() if key not in ("_score", "sort", "_explanation")}
    return fingerprint({"source": source, "id": identity, "snapshot": snapshot})


def register(case, input_path, goal):
    case = outside_skill(case)
    input_bytes = Path(input_path).expanduser().read_bytes()
    data = json.loads(input_bytes.decode("utf-8-sig"))
    if not isinstance(data, dict) or data.get("source") not in ("familysearch", "gwar", "manual"):
        raise SourceError("Нужен JSON локального анализа FamilySearch, поиска GWAR или ручного поиска (source: manual).")
    source = data["source"]
    # Validate the complete input before changing any register.
    items = list({"familysearch": fs_items, "gwar": gwar_items, "manual": manual_items}[source](data))
    coverage = data.get("coverage")
    if source == "manual" and coverage is None:
        # Unknown coverage stays partial; do not force the researcher to invent completeness.
        coverage = {"complete": False}
    if not isinstance(coverage, dict) or type(coverage.get("complete")) is not bool:
        raise SourceError("В результате отсутствует отчёт о покрытии.")
    if source == "familysearch":
        if any(coverage.get(key) for key in ("unresolved_pages", "blocked_pages")):
            coverage = {**coverage, "complete": False}
    for name in ("person-register.csv", "claims-register.csv", "relationship-register.csv", "case-intake.yaml"):
        if not (case / name).is_file():
            raise SourceError("Сначала создайте дело через init_case.py.")
    with state_lock(case / ".register-search.lock"):
        artifact_path, log_path = case / "artifact-register.csv", case / "search-log.csv"
        artifact_fields, artifacts = read_register(artifact_path, "artifact_id")
        log_fields, logs = read_register(log_path, "search_id")
        required_artifact = {"artifact_id", "access_notes", "originality", "directness", "status", "sha256", "independence_group"}
        required_log = {"search_id", "filters", "artifact_ids", "result_status"}
        if not required_artifact.issubset(artifact_fields) or not required_log.issubset(log_fields):
            raise SourceError("Формат реестров не соответствует шаблонам навыка.")
        existing_keys = {}
        artifact_ids, added = [], 0
        for item in items:
            key = snapshot_key(source, item["id"], item["snapshot"])
            marker = "source_key=" + key
            previous = existing_keys.get(key) or next((row for row in artifacts if marker in row.get("access_notes", "")), None)
            if previous:
                artifact_ids.append(previous["artifact_id"])
                continue
            # Save the actual source payload, not just a surname-match excerpt.
            payload = {"source": source, "source_record_id": item["id"], "record": item["snapshot"],
                       "locations": item.get("locations", []), "registered_at": timestamp()}
            snapshot = case / "sources" / source / (key + ".json")
            # Reject symlinks that would put private case material inside the skill.
            outside_skill(snapshot)
            content = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            if snapshot.exists():
                content = snapshot.read_bytes()
                existing = json.loads(content)
                if (existing.get("source_record_id") != item["id"]
                        or without_capture(existing.get("record")) != without_capture(item["snapshot"])):
                    raise SourceError("Сохранённый артефакт не соответствует исходной записи.")
            else:
                atomic_bytes(snapshot, content)
            artifact_id = next_id(artifacts, "artifact_id", "A-")
            row = {field: "" for field in artifact_fields}
            row.update({key: value for key, value in item.items() if key in row})
            row.update({"artifact_id": artifact_id, "captured_at": item["captured_at"] or timestamp(),
                        "source_url_or_path": item["source_url_or_path"] or str(snapshot),
                        "source_type": "unknown" if source == "manual" else "index",
                        "originality": "unknown" if source == "manual" else "index",
                        "directness": "lead-only", "status": "lead-only",
                        "provenance_level": ("Ручная заметка; происхождение первоисточника не проверено"
                                             if source == "manual" else "источник индекса установлен; оригинал не проверен"),
                        "access_notes": f"{marker}; snapshot={snapshot.relative_to(case)}",
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "reliability_notes": "Совпадение — кандидат. Независимость не установлена; назначьте группу исходного документа после проверки."
                        + (" Дата исходного получения неизвестна; captured_at — дата регистрации." if not item["captured_at"] else "")})
            artifacts.append(row)
            existing_keys[key] = row
            artifact_ids.append(artifact_id)
            added += 1
        artifact_ids = list(dict.fromkeys(artifact_ids))
        complete = coverage["complete"] and not data.get("blocked")
        status = "found" if artifact_ids else "not-found"
        if not complete:
            status = "blocked" if data.get("blocked") else "partial"
        log_key = fingerprint({"source": source, "query": data.get("query"), "coverage": coverage,
                               "artifacts": artifact_ids, "goal": goal, "input": fingerprint(data)})
        log_marker = "search_key=" + log_key
        new_log = not any(log_marker in row.get("filters", "") for row in logs)
        if new_log:
            row = {field: "" for field in log_fields}
            row.update({"search_id": next_id(logs, "search_id", "S-"), "timestamp": timestamp(), "research_goal": goal,
                        "query": encode(data.get("query", {"apid": data.get("apid")})),
                        "source_or_domain": {"familysearch": "familysearch.org", "gwar": "gwar.mil.ru"}.get(source) or data["source_or_domain"],
                        "filters": encode({"key": log_marker, "coverage": coverage, "entities": data.get("entities"),
                                           "input": str(Path(input_path).expanduser().resolve()), "sha256": hashlib.sha256(input_bytes).hexdigest()}),
                        "result_status": status, "artifact_ids": ";".join(artifact_ids),
                        "blocker": encode(data["blocked"]) if data.get("blocked") else "",
                        "next_step": "Проверить оригиналы, различить кандидатов и установить независимость; покрытие ограничено указанным набором."})
            logs.append(row)
        # A rerun after an interruption between these writes reuses source_key and search_key.
        save_register(artifact_path, artifact_fields, artifacts)
        save_register(log_path, log_fields, logs)
        return {"added_artifacts": added, "artifact_ids": artifact_ids, "added_search_log": new_log,
                "result_status": status, "claims_created": 0, "persons_created": 0, "relationships_created": 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Записать поисковые находки в существующие реестры как непроверенные артефакты.")
    parser.add_argument("--case-dir", required=True)
    parser.add_argument("--input", required=True, help="Результат FamilySearch browser-import, GWAR search/volost или JSON ручного поиска (source: manual)")
    parser.add_argument("--research-goal", required=True)
    args = parser.parse_args(argv)
    try:
        output_json(register(args.case_dir, args.input, args.research_goal))
        return 0
    except (SourceError, OSError, ValueError, TypeError, KeyError) as exc:
        print("Ошибка: " + (str(exc) if isinstance(exc, SourceError) else "Некорректный файл или ошибка локального ввода/вывода."), file=sys.stderr)
        return 1


if __name__ == "__main__":
    configure_utf8_stdio()
    raise SystemExit(main())
