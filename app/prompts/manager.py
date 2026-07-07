"""Filesystem-backed, versioned prompt library loader and process-lifetime cache."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Protocol

from app.dependencies import get_settings
from app.logging_config import get_logger
from app.prompts.exceptions import PromptNotFoundError
from app.prompts.schemas import PromptRef

logger = get_logger(__name__)

PROMPT_CATEGORIES: tuple[str, ...] = ("system", "classification", "rag", "clarification", "tools", "quotes")

_VERSION_FILENAME_PATTERN = re.compile(r"_v(\d+)\.md$")


class PromptProvider(Protocol):
    """Structural protocol for prompt retrieval, satisfied by PromptManager.

    All callers (Router, RAG Engine, Tool Executor, Clarification, Quote Explainer)
    type-hint against this Protocol rather than importing `PromptManager` directly,
    so a future database-backed prompt provider can be swapped in transparently.
    """

    def get(self, category: str, name: str, version: str) -> str:
        """Return the exact prompt text for a category/name/version."""
        ...

    def get_latest(self, category: str, name: str) -> str:
        """Return the prompt text for the highest integer version present."""
        ...


def _is_safe_path_component(value: str) -> bool:
    return bool(value) and "/" not in value and "\\" not in value and ".." not in value


class PromptManager:
    """Loads and caches versioned prompt files for the lifetime of the process."""

    def __init__(self, library_path: str) -> None:
        # Resolved once, at construction time, so a later change to the process's
        # working directory (e.g. a test doing `monkeypatch.chdir`) can't shift
        # where an already-constructed manager reads its prompts from.
        self.library_path = Path(library_path).resolve()
        self._cache: dict[str, str] = {}

    def get(self, category: str, name: str, version: str) -> str:
        """Return the exact prompt text for one category/name/version."""
        self._validate_lookup(category, name, version)

        cache_key = f"{category}/{name}_{version}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        path = self.library_path / category / f"{name}_v{version}.md"
        return self._read(path, cache_key)

    def get_latest(self, category: str, name: str) -> str:
        """Return the content of the highest integer version file present.

        Uses integer sort on the version number extracted from each filename, not
        string sort, so `v10` correctly outranks `v9`.
        """
        if category not in PROMPT_CATEGORIES:
            raise PromptNotFoundError(f"Unknown prompt category: {category!r}")
        if not _is_safe_path_component(name):
            raise PromptNotFoundError(f"Invalid prompt name: {name!r}")

        directory = self.library_path / category
        best_version: int | None = None
        best_path: Path | None = None
        if directory.is_dir():
            for candidate in directory.glob(f"{name}_v*.md"):
                match = _VERSION_FILENAME_PATTERN.search(candidate.name)
                if match is None:
                    continue
                version_number = int(match.group(1))
                if best_version is None or version_number > best_version:
                    best_version = version_number
                    best_path = candidate

        if best_path is None or best_version is None:
            raise PromptNotFoundError(f"No versioned prompt found for {category}/{name} under {directory}")

        cache_key = f"{category}/{name}_{best_version}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        return self._read(best_path, cache_key)

    def startup_self_check(self, references: list[PromptRef]) -> None:
        """Eagerly load every referenced prompt, failing fast on any missing file."""
        for ref in references:
            self.get(ref.category, ref.name, ref.version)

    def _validate_lookup(self, category: str, name: str, version: str) -> None:
        if category not in PROMPT_CATEGORIES:
            raise PromptNotFoundError(f"Unknown prompt category: {category!r}")
        if not _is_safe_path_component(name):
            raise PromptNotFoundError(f"Invalid prompt name: {name!r}")
        if not _is_safe_path_component(version):
            raise PromptNotFoundError(f"Invalid prompt version: {version!r}")

    def _read(self, path: Path, cache_key: str) -> str:
        logger.debug("prompt_cache_miss", extra={"path": str(path)})
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.error("prompt_not_found", extra={"path": str(path)})
            raise PromptNotFoundError(f"Prompt file not found: {path}") from exc
        self._cache[cache_key] = content
        return content


# The set of prompts every module currently references; validated at startup so a
# missing file is a boot-time failure, not a mid-conversation surprise.
STARTUP_PROMPT_REFERENCES: list[PromptRef] = [
    PromptRef(category="system", name="base", version="1"),
    PromptRef(category="classification", name="classify_intent", version="1"),
    PromptRef(category="classification", name="extract_facts", version="1"),
    PromptRef(category="rag", name="context_inject", version="1"),
    PromptRef(category="rag", name="filter_extract", version="1"),
    PromptRef(category="clarification", name="llm_rewrite_instructions", version="1"),
    PromptRef(category="clarification", name="escalation", version="1"),
    PromptRef(category="tools", name="tool_instructions", version="1"),
    PromptRef(category="quotes", name="quote_explanation", version="1"),
]

# Single module-level singleton — callers import `prompt_manager`, they do not
# instantiate PromptManager themselves.
prompt_manager = PromptManager(get_settings().prompts.library_path)


def register_hooks(app: Any, settings: Any) -> None:
    """Run the startup prompt self-check and expose the shared PromptManager."""
    prompt_manager.startup_self_check(STARTUP_PROMPT_REFERENCES)
    app.state.prompt_manager = prompt_manager
