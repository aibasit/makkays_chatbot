"""Unit tests for Module 08 Prompt Manager."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.prompts.exceptions import PromptNotFoundError
from app.prompts.manager import STARTUP_PROMPT_REFERENCES, PromptManager
from app.prompts.schemas import PromptRef


def _write_prompt(root: Path, category: str, filename: str, content: str) -> None:
    directory = root / category
    directory.mkdir(parents=True, exist_ok=True)
    (directory / filename).write_text(content, encoding="utf-8")


def test_get_returns_correct_prompt_for_version(tmp_path: Path) -> None:
    _write_prompt(tmp_path, "system", "base_v1.md", "v1 content")
    _write_prompt(tmp_path, "system", "base_v2.md", "v2 content")
    manager = PromptManager(str(tmp_path))

    assert manager.get("system", "base", "1") == "v1 content"
    assert manager.get("system", "base", "2") == "v2 content"


def test_get_caches_after_first_load(tmp_path: Path) -> None:
    _write_prompt(tmp_path, "system", "base_v1.md", "original")
    manager = PromptManager(str(tmp_path))
    first = manager.get("system", "base", "1")

    (tmp_path / "system" / "base_v1.md").write_text("changed", encoding="utf-8")
    second = manager.get("system", "base", "1")

    assert first == "original"
    assert second == "original"


def test_get_latest_uses_integer_sort_not_string_sort(tmp_path: Path) -> None:
    _write_prompt(tmp_path, "classification", "classify_intent_v9.md", "v9")
    _write_prompt(tmp_path, "classification", "classify_intent_v10.md", "v10")
    manager = PromptManager(str(tmp_path))

    assert manager.get_latest("classification", "classify_intent") == "v10"


def test_get_missing_prompt_raises_prompt_not_found_error(tmp_path: Path) -> None:
    manager = PromptManager(str(tmp_path))

    with pytest.raises(PromptNotFoundError):
        manager.get("system", "base", "1")


def test_get_rejects_unknown_category(tmp_path: Path) -> None:
    manager = PromptManager(str(tmp_path))

    with pytest.raises(PromptNotFoundError):
        manager.get("not_a_category", "base", "1")


def test_get_latest_raises_when_no_versions_present(tmp_path: Path) -> None:
    manager = PromptManager(str(tmp_path))

    with pytest.raises(PromptNotFoundError):
        manager.get_latest("system", "base")


def test_startup_self_check_validates_all_referenced_prompts(tmp_path: Path) -> None:
    references = [
        PromptRef(category="system", name="base", version="1"),
        PromptRef(category="classification", name="classify_intent", version="1"),
    ]
    for ref in references:
        _write_prompt(tmp_path, ref.category, f"{ref.name}_v{ref.version}.md", "content")
    manager = PromptManager(str(tmp_path))

    manager.startup_self_check(references)


def test_startup_self_check_raises_on_missing_file(tmp_path: Path) -> None:
    _write_prompt(tmp_path, "system", "base_v1.md", "content")
    manager = PromptManager(str(tmp_path))

    with pytest.raises(PromptNotFoundError):
        manager.startup_self_check(
            [
                PromptRef(category="system", name="base", version="1"),
                PromptRef(category="classification", name="classify_intent", version="1"),
            ]
        )


def test_real_prompt_library_satisfies_startup_self_check() -> None:
    """The repo's actual prompt_library/ must satisfy every reference Module 08 declares."""
    from app.prompts.manager import prompt_manager

    prompt_manager.startup_self_check(STARTUP_PROMPT_REFERENCES)
