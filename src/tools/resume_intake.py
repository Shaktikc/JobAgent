"""Task 15: describe resumes in an intake folder, then move them into the pool.

A resume placed in the intake folder (``resumes/new/`` by default) is described
by Task 3.2 first. Only after its LLM description is stored is it moved into the
existing resume pool, where it becomes a normal matching candidate. The
description entry follows the file to its new canonical path, and the resume's
bytes are never changed. No deterministic fallback is used: if the LLM is
unconfigured or a description fails, the file stays in the intake folder.
"""

from __future__ import annotations

import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from src.configuration import Settings

from .resume_descriptions import (
    ResumeDescription,
    ResumeDescriptionError,
    canonical_path,
    description_for,
    ensure_descriptions,
    is_fresh,
    load_descriptions,
    move_description,
)
from .resume_library import RESUME_SUFFIXES, retarget_resume

Describe = Callable[[str | Path], Awaitable[ResumeDescription]]
Notify = Callable[[str], None]


@dataclass
class IntakeFileResult:
    """What happened to one resume in the intake folder."""

    source: str
    destination: str = ""
    status: str = ""  # "described", "reused", "moved", or "failed"
    description_reused: bool = False
    error: str = ""


@dataclass
class IntakeOutcome:
    """Summary of one intake-folder pass (Task 15)."""

    intake_dir: str = ""
    resumes_dir: str = ""
    found: int = 0
    described: int = 0
    reused: int = 0
    moved: int = 0
    failed: int = 0
    files: list[IntakeFileResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when every found resume was handled without an error."""
        return self.failed == 0 and not self.errors

    @property
    def summary(self) -> str:
        """A compact audit line for the Task 3 outcome/log."""
        return (
            f"task15: intake={self.intake_dir} found={self.found} "
            f"described={self.described} reused={self.reused} "
            f"moved={self.moved} failed={self.failed}"
        )


def list_intake_files(intake_dir: str | Path) -> list[Path]:
    """Return the supported resume files directly inside ``intake_dir``."""
    directory = Path(intake_dir)
    if not directory.is_dir():
        return []
    files = [
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in RESUME_SUFFIXES
    ]
    return sorted(files, key=lambda path: path.name.lower())


def _same_dir(left: str | Path, right: str | Path) -> bool:
    """True when two paths resolve to the same folder."""
    try:
        return Path(left).resolve() == Path(right).resolve()
    except OSError:
        return False


def _free_destination(directory: Path, name: str) -> Path:
    """A collision-safe destination path (never an existing file)."""
    path = Path(name)
    stem = path.stem or "resume"
    suffix = path.suffix
    candidate = directory / f"{stem}{suffix}"
    counter = 1
    while candidate.exists():
        candidate = directory / f"{stem} ({counter}){suffix}"
        counter += 1
    return candidate


def move_resume(
    resumes_dir: str | Path,
    intake_path: str | Path,
    store_path: str | Path,
    library_path: str | Path,
) -> Path:
    """Move a described intake resume into ``resumes_dir`` and retarget its store.

    The file is moved only when a stored description exists. The description
    entry is moved from the old canonical path to the new one, and any remembered
    library entry is retargeted. On failure the file and mapping are rolled back
    to the intake path where possible, so a later run can retry cleanly.
    """
    source = Path(intake_path)
    if description_for(load_descriptions(store_path), source) is None:
        raise ResumeDescriptionError(f"no stored description for resume {source}")

    destination = _free_destination(Path(resumes_dir), source.name)
    mapping_moved = False
    try:
        shutil.move(str(source), str(destination))
        entry = move_description(store_path, source, destination)
        if entry is None:
            raise ResumeDescriptionError(f"no stored description for resume {source}")
        mapping_moved = True
        retarget_resume(library_path, source, destination)
    except Exception as exc:
        if mapping_moved:
            try:
                move_description(store_path, destination, source)
            except Exception:  # noqa: BLE001 - best-effort rollback
                pass
        try:
            if destination.exists() and not source.exists():
                shutil.move(str(destination), str(source))
        except OSError:
            pass
        if isinstance(exc, ResumeDescriptionError):
            raise
        raise ResumeDescriptionError(
            f"could not move {source} to {destination}: {exc}"
        ) from exc
    return destination


def _description_is_fresh(store_path: str | Path, path: str | Path) -> bool:
    """True when the store already has a fresh description for ``path``."""
    entry = load_descriptions(store_path).get(canonical_path(path))
    return isinstance(entry, dict) and is_fresh(entry, path)


def _fail(
    outcome: IntakeOutcome, result: IntakeFileResult, path: Path, exc: Exception
) -> None:
    """Record one failed intake file without inventing a description or a move."""
    result.status = "failed"
    result.error = str(exc)
    outcome.failed += 1
    outcome.errors.append(f"{path.name}: {exc}")
    outcome.files.append(result)


async def process_new_resumes(
    resumes_dir: str | Path,
    new_resumes_dir: str | Path | None,
    settings: Settings,
    *,
    describe: Describe | None = None,
    client=None,
    extract_text: Callable[[str | Path], str] | None = None,
    notify: Notify | None = None,
    store_path: str | Path | None = None,
    library_path: str | Path | None = None,
) -> IntakeOutcome:
    """Describe every supported intake resume, then move it into the pool.

    Files with a fresh stored description are moved without another LLM call.
    New or changed files are described by Task 3.2 first. A failure leaves the
    file in the intake folder and records the real error; it is never matched
    from raw text and never overwritten into the main pool.
    """
    notify = notify or (lambda _message: None)
    main_dir = Path(resumes_dir)
    intake_dir = (
        Path(new_resumes_dir)
        if new_resumes_dir is not None
        else (settings.new_resumes_path or main_dir / "new")
    )
    outcome = IntakeOutcome(intake_dir=str(intake_dir), resumes_dir=str(main_dir))
    same_dir = _same_dir(main_dir, intake_dir)
    main_dir.mkdir(parents=True, exist_ok=True)
    if not same_dir:
        intake_dir.mkdir(parents=True, exist_ok=True)

    files = list_intake_files(intake_dir)
    outcome.found = len(files)
    if not files:
        return outcome

    store = store_path or settings.resume_descriptions_file
    library = library_path or settings.resume_library_file
    for path in files:
        result = IntakeFileResult(source=str(path))
        reused = _description_is_fresh(store, path)
        notify(f"Task 15: processing new resume {path.name!r}...")
        try:
            await ensure_descriptions(
                intake_dir,
                store,
                settings,
                files=[path],
                describe=describe,
                client=client,
                extract_text=extract_text,
            )
        except Exception as exc:  # noqa: BLE001 - record the real describe error
            _fail(outcome, result, path, exc)
            continue

        if description_for(load_descriptions(store), path) is None:
            _fail(
                outcome,
                result,
                path,
                ResumeDescriptionError(f"no stored description for resume {path}"),
            )
            continue

        if reused:
            outcome.reused += 1
            result.description_reused = True
        else:
            outcome.described += 1

        if same_dir:
            result.status = "reused" if reused else "described"
            result.destination = str(path)
            outcome.files.append(result)
            continue

        try:
            destination = move_resume(main_dir, path, store, library)
        except Exception as exc:  # noqa: BLE001 - record the real move error
            _fail(outcome, result, path, exc)
            continue

        result.status = "moved"
        result.destination = str(destination)
        outcome.moved += 1
        outcome.files.append(result)
        notify(f"Task 15: moved {path.name!r} to {destination}")

    return outcome


__all__ = [
    "IntakeFileResult",
    "IntakeOutcome",
    "list_intake_files",
    "move_resume",
    "process_new_resumes",
]
