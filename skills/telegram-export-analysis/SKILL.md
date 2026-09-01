---
name: telegram-export-analysis
description: Use when the user provides an official Telegram Desktop JSON export and needs safe local import, incremental full-text search, or analysis of selected chat and channel history without granting a third-party client a Telegram user session.
---

# Telegram Export Analysis

Use this skill only for an export made by the official Telegram Desktop client. It imports the selected export into a local SQLite FTS5 index; it does not authenticate to Telegram or fetch data from the network.

## Scope and Safety

- Accept only a user-provided `result.json` from Telegram Desktop. Do not parse Telegram Desktop's private cache/database, use MTProto, invoke a user-session CLI, or create a Membrane connection for this workflow.
- Confirm the exact chats, date range, and whether media is needed before asking the user to export. Prefer an individual-chat export and omit media unless the task needs it.
- Keep the JSON export and database outside Git in a private directory. The importer refuses a database directory that is group- or world-accessible and sets the database to mode `600`.
- Treat exported messages as confidential data. Do not print a bulk dump, commit it, upload it, or pass the complete export to an external model. Retrieve only the relevant matches and cite their local source fields.

## Obtain an Export

If an export is not already available, the user must perform this official-client step:

1. Open the exact chat in Telegram Desktop.
2. Open the chat's `...` menu and select `Export chat history`.
3. Select `Machine-readable JSON`, choose the requested date/content scope, and complete the export.
4. Provide the resulting `result.json` path. Explain that this produces a local snapshot for offline analysis and does not grant a new application session.

For a broader selected archive, use Telegram Desktop `Settings -> Export Telegram data` with the same JSON and minimum-scope principles.

## Import and Refresh

Read the export's top-level structure before import; do not dump message bodies merely to inspect it. Use the bundled script with an explicit private database location:

```sh
mkdir -m 700 /path/to/private/telegram-index
python3 scripts/telegram_export_index.py import \
  --export /path/to/export/result.json \
  --database /path/to/private/telegram-index/messages.sqlite3
```

The import key is `(chat_id, message_id)`. Re-importing a complete newer export updates edited messages and removes records missing from chat snapshots included in that export. Do not call a partial export a complete snapshot: import it into a separate database or include the affected chat's full history.

## Search

Use FTS5 for exact text, names, tickers, phrases, and date-bounded retrieval:

```sh
python3 scripts/telegram_export_index.py search \
  --database /path/to/private/telegram-index/messages.sqlite3 \
  --query '"exact phrase"' \
  --limit 25
```

The command returns structured JSON with chat, author, date, message ID, and text. Use the smallest useful limit, then narrow by chat/date/query rather than exporting the corpus again. FTS query syntax errors are intentional failures: correct the query rather than silently broadening it.

## Analysis Handoff

When analysis is requested, summarize only retrieved messages and label them `source_scope: my_export`. Keep conclusions separate from quoted evidence. If the task also includes public channels, use `platform-source-research` and preserve its source URLs separately; never merge public-web data with private-export provenance.
