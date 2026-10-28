"""Task 15: describe intake resumes, then move them into the main pool."""

from __future__ import annotations

from pathlib import Path

from src.configuration import SessionSettings, Settings
from src.state import JobDescription
from src.tools.linkedin_best_matching_resume import ensure_resume
from src.tools.resume_descriptions import (
    ResumeDescription,
    ResumeDescriptionError,
    canonical_path,
    description_for,
    load_descriptions,
    store_description,
)
from src.tools.resume_intake import list_intake_files, process_new_resumes
from src.tools.resume_library import load_library, remember_resume


def _settings(tmp_path: Path, **session) -> Settings:
    return Settings(
        session=SessionSettings(**session),
        data_dir=tmp_path,
        resumes_dir=tmp_path,
        resume_library_path=tmp_path / "resume_library.json",
        resume_descriptions_path=tmp_path / "resume_descriptions.json",
    )


def _describer(
    summary: str = "profile",
    *,
    calls: list[str] | None = None,
    fail_for: set[str] | None = None,
):
    async def describe(path):
        name = Path(path).name
        if calls is not None:
            calls.append(name)
        if fail_for and name in fail_for:
            raise ResumeDescriptionError(f"the LLM call failed for {name}")
        return ResumeDescription(summary=summary)

    return describe


def _picks_name(name: str):
    async def pick(_job_description, candidates):
        from src.tools.resume_descriptions import ResumeMatch

        for path, _description in candidates:
            if Path(path).name == name:
                return ResumeMatch(selected_path=path, fit="strong", rationale="best fit")
        return ResumeMatch(fit="none", rationale="nothing fits")

    return pick


def test_list_intake_files_filters_sorts_and_ignores_subdirs(tmp_path) -> None:
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "a.md").write_text("a", encoding="utf-8")
    (tmp_path / "ignore.exe").write_text("nope", encoding="utf-8")
    (tmp_path / "sub").mkdir()

    names = [path.name for path in list_intake_files(tmp_path)]
    assert names == ["a.md", "b.txt"]
    assert list_intake_files(tmp_path / "missing") == []


async def test_process_describes_then_moves_and_rewrites_mapping(tmp_path) -> None:
    main = tmp_path / "resumes"
    intake = main / "new"
    intake.mkdir(parents=True)
    resume = intake / "new_resume.txt"
    resume.write_text("Python AWS", encoding="utf-8")
    settings = _settings(tmp_path)
    settings.resumes_dir = main

    outcome = await process_new_resumes(
        main, intake, settings, describe=_describer("new profile")
    )

    destination = main / "new_resume.txt"
    assert outcome.ok is True
    assert (outcome.found, outcome.described, outcome.reused, outcome.moved) == (1, 1, 0, 1)
    assert not resume.exists()
    assert destination.read_text(encoding="utf-8") == "Python AWS"
    entries = load_descriptions(settings.resume_descriptions_file)
    assert canonical_path(resume) not in entries
    assert description_for(entries, destination).summary == "new profile"


async def test_process_reuses_fresh_description_without_llm(tmp_path) -> None:
    main = tmp_path / "resumes"
    intake = main / "new"
    intake.mkdir(parents=True)
    resume = intake / "keep.txt"
    resume.write_text("Python AWS", encoding="utf-8")
    settings = _settings(tmp_path)
    settings.resumes_dir = main
    store_description(
        settings.resume_descriptions_file,
        resume,
        ResumeDescription(summary="already described"),
    )

    calls: list[str] = []
    outcome = await process_new_resumes(
        main, intake, settings, describe=_describer("unused", calls=calls)
    )

    assert outcome.reused == 1
    assert outcome.described == 0
    assert calls == []
    assert (main / "keep.txt").exists()
    entries = load_descriptions(settings.resume_descriptions_file)
    assert description_for(entries, main / "keep.txt").summary == "already described"


async def test_process_redescribes_a_changed_file(tmp_path) -> None:
    main = tmp_path / "resumes"
    intake = main / "new"
    intake.mkdir(parents=True)
    resume = intake / "changed.txt"
    resume.write_text("Python", encoding="utf-8")
    settings = _settings(tmp_path)
    settings.resumes_dir = main
    store_description(
        settings.resume_descriptions_file, resume, ResumeDescription(summary="old")
    )
    resume.write_text("Python AWS", encoding="utf-8")  # changed size

    calls: list[str] = []
    outcome = await process_new_resumes(
        main, intake, settings, describe=_describer("new", calls=calls)
    )

    assert outcome.described == 1
    assert calls == ["changed.txt"]
    entries = load_descriptions(settings.resume_descriptions_file)
    assert description_for(entries, main / "changed.txt").summary == "new"


async def test_process_collision_does_not_overwrite(tmp_path) -> None:
    main = tmp_path / "resumes"
    intake = main / "new"
    intake.mkdir(parents=True)
    existing = main / "same.txt"
    existing.write_text("old", encoding="utf-8")
    resume = intake / "same.txt"
    resume.write_text("new", encoding="utf-8")
    settings = _settings(tmp_path)
    settings.resumes_dir = main

    outcome = await process_new_resumes(main, intake, settings, describe=_describer())

    moved = main / "same (1).txt"
    assert outcome.moved == 1
    assert existing.read_text(encoding="utf-8") == "old"
    assert moved.read_text(encoding="utf-8") == "new"
    entries = load_descriptions(settings.resume_descriptions_file)
    assert description_for(entries, moved) is not None


async def test_process_description_failure_keeps_file_and_no_mapping(tmp_path) -> None:
    main = tmp_path / "resumes"
    intake = main / "new"
    intake.mkdir(parents=True)
    resume = intake / "bad.txt"
    resume.write_text("Python", encoding="utf-8")
    settings = _settings(tmp_path)
    settings.resumes_dir = main

    outcome = await process_new_resumes(
        main, intake, settings, describe=_describer(fail_for={"bad.txt"})
    )

    assert outcome.ok is False
    assert outcome.failed == 1
    assert outcome.moved == 0
    assert resume.exists()
    assert not (main / "bad.txt").exists()
    entries = load_descriptions(settings.resume_descriptions_file)
    assert description_for(entries, resume) is None
    assert outcome.errors


async def test_process_move_failure_keeps_file_and_intake_mapping(
    tmp_path, monkeypatch
) -> None:
    main = tmp_path / "resumes"
    intake = main / "new"
    intake.mkdir(parents=True)
    resume = intake / "locked.txt"
    resume.write_text("Python", encoding="utf-8")
    settings = _settings(tmp_path)
    settings.resumes_dir = main

    def fail_move(*_args, **_kwargs):
        raise OSError("file is locked")

    monkeypatch.setattr("src.tools.resume_intake.shutil.move", fail_move)
    outcome = await process_new_resumes(main, intake, settings, describe=_describer())

    assert outcome.ok is False
    assert outcome.failed == 1
    assert resume.exists()
    entries = load_descriptions(settings.resume_descriptions_file)
    assert description_for(entries, resume) is not None
    assert not (main / "locked.txt").exists()


async def test_process_updates_remembered_library_path(tmp_path) -> None:
    main = tmp_path / "resumes"
    intake = main / "new"
    intake.mkdir(parents=True)
    resume = intake / "remembered.txt"
    resume.write_text("Python", encoding="utf-8")
    settings = _settings(tmp_path)
    settings.resumes_dir = main
    remember_resume(
        settings.resume_library_file,
        JobDescription(title="Python Engineer", body="Python"),
        str(resume),
    )

    outcome = await process_new_resumes(main, intake, settings, describe=_describer())

    assert outcome.moved == 1
    library = load_library(settings.resume_library_file)
    assert library[0]["resume"] == str(main / "remembered.txt")


async def test_process_same_directory_describes_without_moving(tmp_path) -> None:
    main = tmp_path / "resumes"
    main.mkdir()
    resume = main / "in_place.txt"
    resume.write_text("Python", encoding="utf-8")
    settings = _settings(tmp_path)
    settings.resumes_dir = main

    outcome = await process_new_resumes(main, main, settings, describe=_describer())

    assert outcome.described == 1
    assert outcome.moved == 0
    assert resume.exists()
    entries = load_descriptions(settings.resume_descriptions_file)
    assert description_for(entries, resume) is not None


async def test_ensure_resume_processes_intake_then_matches_moved_resume(tmp_path) -> None:
    intake = tmp_path / "new"
    intake.mkdir()
    (intake / "new_python.txt").write_text("Python AWS", encoding="utf-8")
    (tmp_path / "old_pastry.txt").write_text("pastry", encoding="utf-8")
    settings = _settings(tmp_path)

    outcome = await ensure_resume(
        JobDescription(title="Python Engineer", body="Python AWS"),
        tmp_path,
        settings,
        describer=_describer("python profile"),
        matcher=_picks_name("new_python.txt"),
        new_resumes_dir=intake,
    )

    assert outcome.error == ""
    assert outcome.selected_path == str(tmp_path / "new_python.txt")
    assert not (intake / "new_python.txt").exists()
    assert "task15:" in outcome.notes
    assert outcome.resumes_found == 2


async def test_ensure_resume_stops_when_intake_description_fails(tmp_path) -> None:
    intake = tmp_path / "new"
    intake.mkdir()
    bad = intake / "bad.txt"
    bad.write_text("Python", encoding="utf-8")
    settings = _settings(tmp_path)
    calls: list[str] = []

    async def matcher(_job_description, candidates):
        calls.append("matcher")
        return await _picks_name("bad.txt")(_job_description, candidates)

    outcome = await ensure_resume(
        JobDescription(title="Python Engineer", body="Python"),
        tmp_path,
        settings,
        describer=_describer(fail_for={"bad.txt"}),
        matcher=matcher,
        new_resumes_dir=intake,
    )

    assert outcome.error
    assert outcome.selected_path is None
    assert calls == []
    assert bad.exists()
    assert "could not process the new-resumes folder" in outcome.notes


def test_settings_new_resumes_dir_defaults_under_resumes(tmp_path) -> None:
    settings = _settings(tmp_path)
    assert settings.new_resumes_dir == tmp_path / "new"


def test_parse_args_describe_new_resumes() -> None:
    from src.main import _parse_args

    args = _parse_args(["--describe-new-resumes"])
    assert args.describe_new_resumes is True
    assert _parse_args([]).describe_new_resumes is False


async def test_describe_new_resumes_cli_reports_and_exits(
    tmp_path, monkeypatch, capsys
) -> None:
    import argparse

    from src import main as cli
    from src.tools.resume_intake import IntakeFileResult, IntakeOutcome

    settings = _settings(tmp_path)
    monkeypatch.setattr(cli, "load_settings", lambda: settings)

    async def fake_process(_resumes_dir, _intake_dir, _settings, **_kwargs):
        return IntakeOutcome(
            intake_dir=str(tmp_path / "new"),
            resumes_dir=str(tmp_path),
            found=1,
            described=1,
            moved=1,
            files=[
                IntakeFileResult(
                    source=str(tmp_path / "new" / "a.txt"),
                    destination=str(tmp_path / "a.txt"),
                    status="moved",
                )
            ],
        )

    monkeypatch.setattr("src.tools.resume_intake.process_new_resumes", fake_process)
    code = await cli._describe_new_resumes(
        argparse.Namespace(resumes_dir=str(tmp_path))
    )

    output = capsys.readouterr().out
    assert code == 0
    assert "described   : 1" in output
    assert "moved       : 1" in output
    assert "a.txt: moved" in output
