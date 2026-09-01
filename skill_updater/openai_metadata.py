from __future__ import annotations

import json
import re
from pathlib import Path


class OpenAIMetadataError(ValueError):
    pass


def _display_name(skill_name: str) -> str:
    acronyms = {"api", "ci", "cli", "github", "llm", "mcp", "pdf", "pr", "sql", "ui", "url"}
    return " ".join(word.upper() if word in acronyms else word.capitalize() for word in skill_name.split("-"))


def _short_description(display_name: str) -> str:
    description = f"Help with {display_name} tasks and workflows"
    if len(description) > 64:
        description = f"Help with {display_name}"
    if len(description) > 64:
        description = f"{display_name[:57].rstrip()} helper"
    if len(description) < 25:
        description = f"{description} and workflows"
    return description[:64].rstrip()


def _interface_value(content: str, key: str) -> str | None:
    match = re.search(rf"^  {re.escape(key)}:\s*(.+?)\s*$", content, re.MULTILINE)
    if not match:
        return None
    raw = match.group(1)
    if raw.startswith('"'):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OpenAIMetadataError(f"agents/openai.yaml has invalid {key}") from exc
        return value if isinstance(value, str) else None
    return raw.strip("'\"")


def validate_openai_yaml(root: Path, skill_name: str) -> None:
    path = root / "agents/openai.yaml"
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OpenAIMetadataError("missing agents/openai.yaml") from exc
    if not re.search(r"^interface:\s*$", content, re.MULTILINE):
        raise OpenAIMetadataError("agents/openai.yaml requires interface")
    display_name = _interface_value(content, "display_name")
    short_description = _interface_value(content, "short_description")
    if not display_name:
        raise OpenAIMetadataError("agents/openai.yaml requires interface.display_name")
    if not short_description or not 25 <= len(short_description) <= 64:
        length = 0 if short_description is None else len(short_description)
        raise OpenAIMetadataError(
            f"agents/openai.yaml short_description must be 25-64 characters; got {length}"
        )
    default_prompt = _interface_value(content, "default_prompt")
    if default_prompt is not None and f"${skill_name}" not in default_prompt:
        raise OpenAIMetadataError(f"agents/openai.yaml default_prompt must mention ${skill_name}")


def ensure_openai_yaml(root: Path, skill_name: str) -> bool:
    path = root / "agents/openai.yaml"
    if path.exists():
        validate_openai_yaml(root, skill_name)
        return False
    display_name = _display_name(skill_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    values = {
        "display_name": display_name,
        "short_description": _short_description(display_name),
        "default_prompt": f"Use ${skill_name} to help with a relevant task.",
    }
    path.write_text(
        "interface:\n"
        + "\n".join(f"  {key}: {json.dumps(value, ensure_ascii=False)}" for key, value in values.items())
        + "\n",
        encoding="utf-8",
    )
    validate_openai_yaml(root, skill_name)
    return True
