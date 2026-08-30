"""Helpers for seeding and validating FSNotes local state in an iOS simulator."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from platforms.ios.runtime_env.simulator_manager import get_app_data_container_path


DEFAULT_BUNDLE_ID = "co.fluder.mobile.FSNotes-iOS"
DEFAULT_NOTES_ROOT_NAME = "Documents"
DEFAULT_NOTE_EXTENSION = ".md"
TRASH_DIRECTORY_NAME = "Trash"
SUPPORTED_NOTE_EXTENSIONS = {
    ".md",
    ".markdown",
    ".mmd",
    ".multimarkdown",
    ".mdown",
    ".mkdn",
    ".mkd",
    ".mdwn",
    ".mdtxt",
    ".mdtext",
    ".mdml",
    ".txt",
}
MARKDOWN_COMPATIBLE_EXTENSIONS = SUPPORTED_NOTE_EXTENSIONS - {".txt"}


@dataclass(frozen=True)
class FSNotesNoteRecord:
    """Materialized note file from the FSNotes storage directory."""

    absolute_path: Path
    relative_path: str
    folder: str
    file_name: str
    stem: str
    extension: str
    content: str

    @property
    def title_candidates(self) -> set[str]:
        candidates = {_normalize_title(self.stem)}
        first_line = _first_non_empty_line(self.content)
        if first_line:
            candidates.add(_normalize_title(first_line))
            stripped_heading = first_line.lstrip("#").strip()
            if stripped_heading:
                candidates.add(_normalize_title(stripped_heading))
        return {candidate for candidate in candidates if candidate}


class FSNotesStore:
    """Read and write FSNotes notes directly from the simulator sandbox."""

    def __init__(
        self,
        notes_root_path: str | Path,
        *,
        bundle_id: str = DEFAULT_BUNDLE_ID,
        data_container_path: str | Path | None = None,
    ) -> None:
        self.notes_root_path = Path(notes_root_path).expanduser().resolve()
        self.bundle_id = str(bundle_id or DEFAULT_BUNDLE_ID).strip() or DEFAULT_BUNDLE_ID
        self.data_container_path = (
            Path(data_container_path).expanduser().resolve()
            if data_container_path is not None
            else self.notes_root_path.parent
        )

    @classmethod
    def from_simulator(
        cls,
        udid: str,
        *,
        bundle_id: str = DEFAULT_BUNDLE_ID,
        notes_root_name: str = DEFAULT_NOTES_ROOT_NAME,
    ) -> "FSNotesStore":
        data_container_path = Path(get_app_data_container_path(udid, bundle_id)).expanduser().resolve()
        notes_root_path = data_container_path / str(notes_root_name or DEFAULT_NOTES_ROOT_NAME).strip()
        return cls(
            notes_root_path=notes_root_path,
            bundle_id=bundle_id,
            data_container_path=data_container_path,
        )

    def seed(self, spec: Mapping[str, Any]) -> dict[str, Any]:
        normalized_spec = dict(spec or {})
        if bool(normalized_spec.get("purge_all_notes", False)):
            self.purge_all_notes()
        else:
            self.ensure_notes_root()

        for folder_spec in self._coerce_mapping_list(normalized_spec.get("folders")):
            self.create_folder(folder_spec)

        created_paths: list[str] = []
        for note_spec in self._coerce_mapping_list(normalized_spec.get("notes")):
            created_paths.append(self.write_note(note_spec).relative_path)

        return {
            "note_count": len(self.list_notes()),
            "folder_count": len(self.list_folders()),
            "created_note_paths": created_paths,
        }

    def assert_state(self, spec: Mapping[str, Any]) -> dict[str, Any]:
        normalized_spec = dict(spec or {})
        observed_notes = self.list_notes(include_trash=bool(normalized_spec.get("include_trash", False)))
        observed_folders = self.list_folders(include_trash=bool(normalized_spec.get("include_trash", False)))
        failures: list[str] = []

        expected_note_count = normalized_spec.get("note_count")
        if expected_note_count is not None:
            try:
                resolved_note_count = int(expected_note_count)
            except (TypeError, ValueError):
                raise ValueError(f"Invalid note_count expectation: {expected_note_count!r}") from None
            if len(observed_notes) != resolved_note_count:
                failures.append(f"note_count expected {resolved_note_count} but got {len(observed_notes)}")

        expected_folder_count = normalized_spec.get("folder_count")
        if expected_folder_count is not None:
            try:
                resolved_folder_count = int(expected_folder_count)
            except (TypeError, ValueError):
                raise ValueError(f"Invalid folder_count expectation: {expected_folder_count!r}") from None
            if len(observed_folders) != resolved_folder_count:
                failures.append(f"folder_count expected {resolved_folder_count} but got {len(observed_folders)}")

        present_folders = self._coerce_text_list(normalized_spec.get("present_folders"))
        absent_folders = self._coerce_text_list(normalized_spec.get("absent_folders"))
        folder_set = {_normalize_relative_path(path) for path in observed_folders}
        for folder in present_folders:
            if _normalize_relative_path(folder) not in folder_set:
                failures.append(f"missing folder: {folder}")
        for folder in absent_folders:
            if _normalize_relative_path(folder) in folder_set:
                failures.append(f"unexpected folder still present: {folder}")

        for note_spec in self._coerce_mapping_list(normalized_spec.get("present_notes")):
            match = next((note for note in observed_notes if self.note_matches_expectation(note, note_spec)), None)
            if match is None:
                failures.append(f"missing note: {self._describe_note_expectation(note_spec)}")

        for note_spec in self._coerce_mapping_list(normalized_spec.get("absent_notes")):
            match = next((note for note in observed_notes if self.note_matches_expectation(note, note_spec)), None)
            if match is not None:
                failures.append(
                    f"unexpected note still present: {self._describe_note_expectation(note_spec)}"
                )

        return {
            "status": "pass" if not failures else "fail",
            "failures": failures,
            "summary": self.summary(observed_notes=observed_notes, observed_folders=observed_folders),
        }

    def summary(
        self,
        *,
        observed_notes: list[FSNotesNoteRecord] | None = None,
        observed_folders: list[str] | None = None,
    ) -> dict[str, Any]:
        notes = observed_notes if observed_notes is not None else self.list_notes()
        folders = observed_folders if observed_folders is not None else self.list_folders()
        return {
            "notes_root_path": str(self.notes_root_path),
            "note_count": len(notes),
            "folder_count": len(folders),
            "note_paths": [note.relative_path for note in notes],
            "folders": folders,
        }

    def ensure_notes_root(self) -> None:
        self.notes_root_path.mkdir(parents=True, exist_ok=True)
        (self.notes_root_path / TRASH_DIRECTORY_NAME).mkdir(parents=True, exist_ok=True)

    def purge_all_notes(self) -> None:
        if self.notes_root_path.exists():
            for child in self.notes_root_path.iterdir():
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
        self.ensure_notes_root()

    def create_folder(self, spec: Mapping[str, Any]) -> str:
        raw_path = str(spec.get("path") or spec.get("folder") or "").strip()
        if not raw_path:
            raise ValueError("FSNotes folder spec requires 'path' or 'folder'")
        folder_path = self._resolve_relative_path(raw_path, expect_directory=True)
        folder_path.mkdir(parents=True, exist_ok=True)
        return folder_path.relative_to(self.notes_root_path).as_posix()

    def write_note(self, spec: Mapping[str, Any]) -> FSNotesNoteRecord:
        note_path = self._note_path_from_spec(spec)
        note_path.parent.mkdir(parents=True, exist_ok=True)
        content = self._note_content_from_spec(spec)
        note_path.write_text(content, encoding="utf-8")
        return self._build_note_record(note_path)

    def list_notes(self, *, include_trash: bool = False) -> list[FSNotesNoteRecord]:
        if not self.notes_root_path.exists():
            return []

        notes: list[FSNotesNoteRecord] = []
        for path in sorted(self.notes_root_path.rglob("*")):
            if not path.is_file() or path.name.startswith("."):
                continue
            relative_path = path.relative_to(self.notes_root_path).as_posix()
            if not include_trash and self._is_in_trash(relative_path):
                continue
            if path.suffix.lower() not in SUPPORTED_NOTE_EXTENSIONS:
                continue
            notes.append(self._build_note_record(path))
        return notes

    def list_folders(self, *, include_trash: bool = False) -> list[str]:
        if not self.notes_root_path.exists():
            return []

        folders: list[str] = []
        for path in sorted(self.notes_root_path.rglob("*")):
            if not path.is_dir() or path == self.notes_root_path or path.name.startswith("."):
                continue
            relative_path = path.relative_to(self.notes_root_path).as_posix()
            if not include_trash and self._is_in_trash(relative_path):
                continue
            folders.append(relative_path)
        return folders

    def clear_saved_state(self) -> None:
        candidates = [
            self.data_container_path
            / "Library"
            / "Saved Application State"
            / f"{self.bundle_id}.savedState",
            self.data_container_path
            / "Library"
            / "SplashBoard"
            / "Snapshots"
            / f"sceneID:{self.bundle_id}-default",
            self.data_container_path
            / "Library"
            / "SplashBoard"
            / "Snapshots"
            / f"{self.bundle_id} - {{DEFAULT GROUP}}",
        ]
        for candidate in candidates:
            if candidate.exists():
                shutil.rmtree(candidate, ignore_errors=True)

    def note_matches_expectation(self, note: FSNotesNoteRecord, expected: Mapping[str, Any]) -> bool:
        expected_path = str(expected.get("path") or "").strip()
        if expected_path and not _relative_path_matches(note.relative_path, expected_path):
            return False

        expected_folder = str(expected.get("folder") or "").strip()
        if expected_folder and _normalize_relative_path(note.folder) != _normalize_relative_path(expected_folder):
            return False

        expected_extension = str(expected.get("extension") or "").strip().lower()
        if expected_extension and not expected_extension.startswith("."):
            expected_extension = f".{expected_extension}"
        if expected_extension and note.extension.lower() != expected_extension:
            return False

        expected_title = str(expected.get("title") or "").strip()
        if expected_title and _normalize_title(expected_title) not in note.title_candidates:
            return False

        exact_content = expected.get("exact_content")
        if exact_content is not None and not _content_matches_exact(note, str(exact_content)):
            return False

        content_contains = self._coerce_text_list(expected.get("content_contains"))
        for fragment in content_contains:
            if fragment not in note.content:
                return False

        content_not_contains = self._coerce_text_list(expected.get("content_not_contains"))
        for fragment in content_not_contains:
            if fragment in note.content:
                return False

        return True

    def _build_note_record(self, path: Path) -> FSNotesNoteRecord:
        relative_path = path.relative_to(self.notes_root_path).as_posix()
        folder = path.relative_to(self.notes_root_path).parent.as_posix()
        if folder == ".":
            folder = ""
        return FSNotesNoteRecord(
            absolute_path=path,
            relative_path=relative_path,
            folder=folder,
            file_name=path.name,
            stem=path.stem,
            extension=path.suffix,
            content=path.read_text(encoding="utf-8"),
        )

    def _note_path_from_spec(self, spec: Mapping[str, Any]) -> Path:
        raw_path = str(spec.get("path") or "").strip()
        if raw_path:
            return self._resolve_relative_path(raw_path, default_extension=str(spec.get("extension") or "").strip())

        title = str(spec.get("title") or "").strip()
        if not title:
            raise ValueError("FSNotes note spec requires 'path' or 'title'")

        raw_folder = str(spec.get("folder") or "").strip()
        extension = str(spec.get("extension") or DEFAULT_NOTE_EXTENSION).strip() or DEFAULT_NOTE_EXTENSION
        if not extension.startswith("."):
            extension = f".{extension}"
        if raw_folder:
            composed = f"{raw_folder.rstrip('/')}/{title}{extension}"
        else:
            composed = f"{title}{extension}"
        return self._resolve_relative_path(composed)

    def _note_content_from_spec(self, spec: Mapping[str, Any]) -> str:
        if "content" in spec:
            return str(spec.get("content") or "")
        return str(spec.get("body") or "")

    def _resolve_relative_path(
        self,
        raw_path: str,
        *,
        default_extension: str = DEFAULT_NOTE_EXTENSION,
        expect_directory: bool = False,
    ) -> Path:
        cleaned = raw_path.replace("\\", "/").strip().strip("/")
        if not cleaned:
            raise ValueError("Relative path must not be empty")
        candidate = self.notes_root_path / cleaned
        if not expect_directory and candidate.suffix == "":
            resolved_extension = default_extension.strip()
            if resolved_extension:
                if not resolved_extension.startswith("."):
                    resolved_extension = f".{resolved_extension}"
                candidate = candidate.with_suffix(resolved_extension)
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.notes_root_path)
        except ValueError as exc:
            raise ValueError(f"Path escapes FSNotes notes root: {raw_path}") from exc
        return resolved

    @staticmethod
    def _is_in_trash(relative_path: str) -> bool:
        parts = Path(relative_path).parts
        return bool(parts) and parts[0] == TRASH_DIRECTORY_NAME

    @staticmethod
    def _coerce_mapping_list(raw: Any) -> list[Mapping[str, Any]]:
        if not isinstance(raw, list):
            return []
        return [item for item in raw if isinstance(item, Mapping)]

    @staticmethod
    def _coerce_text_list(raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []
        values: list[str] = []
        for item in raw:
            text = str(item or "")
            if text.strip():
                values.append(text)
        return values

    @staticmethod
    def _describe_note_expectation(spec: Mapping[str, Any]) -> str:
        payload = {
            key: value
            for key, value in spec.items()
            if key in {"path", "folder", "title", "extension", "content_contains", "content_not_contains"}
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _normalize_title(value: str) -> str:
    return " ".join(str(value or "").replace("\n", " ").split()).strip().casefold()


def _normalize_relative_path(value: str) -> str:
    text = str(value or "").replace("\\", "/").strip().strip("/")
    if not text or text == ".":
        return ""
    return Path(text).as_posix()


def _normalize_newlines(value: str) -> str:
    return str(value).replace("\r\n", "\n").replace("\r", "\n")


def _relative_path_matches(actual: str, expected: str) -> bool:
    actual_path = _normalize_relative_path(actual)
    expected_path = _normalize_relative_path(expected)
    if actual_path == expected_path:
        return True

    actual_parts = Path(actual_path)
    expected_parts = Path(expected_path)
    if actual_parts.parent != expected_parts.parent:
        return False
    if _normalize_title(actual_parts.stem) != _normalize_title(expected_parts.stem):
        return False

    actual_suffix = actual_parts.suffix.lower()
    expected_suffix = expected_parts.suffix.lower()
    if not expected_suffix:
        return actual_suffix in MARKDOWN_COMPATIBLE_EXTENSIONS
    return (
        actual_suffix in MARKDOWN_COMPATIBLE_EXTENSIONS
        and expected_suffix in MARKDOWN_COMPATIBLE_EXTENSIONS
    )


def _content_matches_exact(note: FSNotesNoteRecord, expected: str) -> bool:
    actual = _normalize_newlines(note.content).rstrip("\n")
    wanted = _normalize_newlines(expected).rstrip("\n")
    if actual == wanted:
        return True

    if "\n" not in actual:
        return False

    first_line, remainder = actual.split("\n", 1)
    if _normalize_title(first_line.lstrip("#").strip()) not in note.title_candidates:
        return False
    return remainder.lstrip("\n").rstrip("\n") == wanted


def _first_non_empty_line(content: str) -> str:
    for line in _normalize_newlines(content).splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""
