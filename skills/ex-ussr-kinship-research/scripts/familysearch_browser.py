"""Analyze targeted FamilySearch evidence fragments."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from pathlib import Path

from research_common import SourceError, timestamp


def fs_url(value, kind=None):
    parsed = urllib.parse.urlsplit(value or "")
    if parsed.scheme != "https" or parsed.netloc not in ("www.familysearch.org", "familysearch.org"):
        raise SourceError("Нужна HTTPS-ссылка FamilySearch без учётных данных в URL.")
    if kind and not re.fullmatch(r"/ark:/61903/" + re.escape(kind) + r":[^/]+", parsed.path):
        raise SourceError("Проверьте устойчивую ссылку записи или изображения FamilySearch.")
    return parsed


def snapshot_rows(snapshot, pages):
    rows, scope = snapshot.get("rows"), snapshot.get("scope")
    if not isinstance(rows, list) or not isinstance(scope, dict):
        raise SourceError("Браузерный фрагмент должен содержать url, scope и rows.")
    fs_url(snapshot.get("url"))
    state = snapshot.get("index_state", "indexed" if rows else "unresolved")
    if state not in ("indexed", "not-indexed", "unresolved", "blocked"):
        raise SourceError("Неизвестное состояние индекса.")
    if snapshot.get("loading"):
        state = "unresolved"
    evidence = snapshot.get("state_evidence", "")
    if not isinstance(evidence, str):
        raise SourceError("state_evidence должен содержать наблюдённый текст источника.")
    if state == "not-indexed" and not evidence.strip():
        raise SourceError("Отсутствие индекса требует явного сообщения источника в state_evidence.")
    if (state == "indexed") != bool(rows):
        raise SourceError("Состояние индекса не соответствует строкам; не сохраняйте незагруженные строки как проверенные.")
    context = {"url": snapshot["url"], "scope": scope, "captured_at": snapshot.get("captured_at", ""),
               "index_state": state, "state_evidence": evidence}
    pages.append(context)
    return [(row, context) for row in rows]


def browser_import(files, patterns):
    candidates, registry, hits, pages, seen = [], [], {}, [], {}
    rows, inputs = [], []
    for path in files:
        path = Path(path).expanduser()
        content = path.read_bytes()
        snapshot = json.loads(content.decode("utf-8-sig"))
        inputs.append({"path": str(path.resolve()), "sha256": hashlib.sha256(content).hexdigest()})
        if not isinstance(snapshot, dict):
            raise SourceError("Некорректный браузерный фрагмент.")
        rows.extend(snapshot_rows(snapshot, pages))
    for row, context in rows:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not row["name"].strip() or not isinstance(row.get("text"), str):
            raise SourceError("В браузерной строке нужны исходные name, text и ссылка.")
        observed_id = row.get("observed_id")
        if observed_id is not None and (not isinstance(observed_id, str) or not observed_id.strip()):
            raise SourceError("Локальный observed_id должен быть непустой строкой.")
        parsed = fs_url(row.get("url"), "3:1" if observed_id else "1:1")
        if row.get("image_url"):
            fs_url(row["image_url"], "3:1")
        ark = "" if observed_id else parsed.path.split("1:1:")[-1]
        rid = "browser-observation:" + observed_id if observed_id else ark
        original = {k: row[k] for k in ("name", "text", "url", "image_url", "people", "observed_id") if k in row}
        if rid in seen:
            if seen[rid] != original:
                raise SourceError("Браузерные строки одной записи различаются; сохраните версии раздельно.")
            continue
        seen[rid] = original
        people = row.get("people") or [{"name": row["name"]}]
        if not isinstance(people, list) or any(not isinstance(p, dict) or not isinstance(p.get("name"), str) or not p["name"] for p in people):
            raise SourceError("Некорректный список наблюдённых имён.")
        persons = {(f"observed-{i}" if row.get("people") else "principal"): {"name": p["name"], "names": [p["name"]], "ark": ark if i == 1 else "",
                    "principal": i == 1, "indexed_label": p.get("label", "")}
                   for i, p in enumerate(people, 1)}
        matches = []
        for layer, label, regex in patterns:
            person_matches = [pid for pid, person in persons.items() if regex.search(person["name"])]
            if regex.search(row["text"]) or person_matches:
                for pid in person_matches or [None]:
                    match = {"rid": rid, "pid": pid, "name": persons[pid]["name"] if pid else row["name"],
                             "principal": persons[pid]["principal"] if pid else None, "ark": ark,
                             "layer": layer, "label": label, "match_scope": "observed-fragment"}
                    hits.setdefault(label, []).append(match)
                    matches.append(match)
        registry.append({"rid": rid, "name": row["name"], "ark": ark, "indexed_text": row["text"], "url": row["url"]})
        if patterns and not matches:
            continue
        record = {"persons": persons,
                  "browser_text": row["text"], "browser_url": row["url"],
                  "identifier_kind": "local-browser-observation" if observed_id else "record-ark",
                  "captured_at": context["captured_at"], "raw": {"browser_row": original}}
        location = {"page_url": context["url"], "image_url": row.get("image_url", ""), "scope": context["scope"]}
        candidates.append({"rid": rid, "record": record, "locations": [location], "matches": matches})
    report = {"complete": False, "scope": "targeted-browser-fragments", "observed_rows": len(seen),
              "matched_rows": len(candidates), "pages": pages, "index_completeness": "not-established",
              "unresolved_pages": [p["url"] for p in pages if p["index_state"] == "unresolved"],
              "not_indexed_pages": [p["url"] for p in pages if p["index_state"] == "not-indexed"],
              "blocked_pages": [p["url"] for p in pages if p["index_state"] == "blocked"]}
    return {"source": "familysearch", "transport": "browser", "analyzed_at": timestamp(), "registry": registry,
            "hits": hits, "candidates": candidates, "inputs": inputs, "query": [{"layer": layer, "label": label, "pattern": regex.pattern}
            for layer, label, regex in patterns], "coverage": report}
