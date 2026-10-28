"""Unit tests for ``scripts/self_heal_repair.py`` (Task 11 repair hook wiring).

The wrapper turns the failure bundle the self-healing loop passes in its
environment into an ``opencode run`` invocation. These tests never launch a real
agent: ``subprocess.run`` is replaced with a recorder.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.self_heal_repair import (
    DEFAULT_REPAIR_MODEL,
    SKILL_FILE,
    build_prompt,
    main,
    resolve_model,
    resolve_opencode,
)


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    """A minimal evidence bundle the loop would have written."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "report.md").write_text("# failure report", encoding="utf-8")
    return bundle


def _set_loop_env(monkeypatch, bundle: Path, *, report: Path | None = None) -> Path:
    report = report or (bundle / "report.md")
    monkeypatch.setenv("AUTOJOB_FAILURE_BUNDLE", str(bundle))
    monkeypatch.setenv("AUTOJOB_FAILURE_REPORT", str(report))
    monkeypatch.setenv("AUTOJOB_FAILURE_FINGERPRINT", "abc123def456")
    monkeypatch.setenv("AUTOJOB_FAILURE_CATEGORY", "form_did_not_advance")
    monkeypatch.setenv("AUTOJOB_BUG_ID", "BUG-099")
    monkeypatch.setenv("AUTOJOB_SELF_HEAL_OPENCODE", str(bundle / "fake-opencode"))
    return report


def test_build_prompt_names_the_evidence_and_the_rules() -> None:
    prompt = build_prompt(
        bundle=Path("C:/bundle"),
        report=Path("C:/bundle/report.md"),
        bug_id="BUG-099",
        fingerprint="abc123def456",
        category="form_did_not_advance",
    )
    assert "BUG-099" in prompt
    assert "abc123def456" in prompt
    assert "form_did_not_advance" in prompt
    assert str(Path("C:/bundle")) in prompt
    assert "failure.json" in prompt
    assert "AGENTS.md" in prompt
    assert "bug_log.md" in prompt
    # The repair agent must always apply the incremental-implementation skill.
    assert "incremental-implementation" in prompt
    assert str(SKILL_FILE) in prompt
    # The repair agent must obey the same hard rules as the live agent.
    assert "Submit application" in prompt
    assert "commit" in prompt
    assert "415 lines" in prompt
    # Non-interactive: a repair must never block on an approval question.
    assert "never ask the user a question" in prompt
    assert "do not edit files under `task/`" in prompt


def test_resolve_opencode_honors_the_override(monkeypatch) -> None:
    monkeypatch.setenv("AUTOJOB_SELF_HEAL_OPENCODE", "C:/tools/opencode.cmd")
    assert resolve_opencode() == ["C:/tools/opencode.cmd"]


def test_resolve_opencode_falls_back_to_path(monkeypatch) -> None:
    monkeypatch.delenv("AUTOJOB_SELF_HEAL_OPENCODE", raising=False)
    monkeypatch.setattr(
        "scripts.self_heal_repair.shutil.which",
        lambda name: "C:/tools/opencode.cmd" if name == "opencode.cmd" else None,
    )
    assert resolve_opencode() == ["C:/tools/opencode.cmd"]


def test_resolve_opencode_explains_a_missing_cli(monkeypatch) -> None:
    monkeypatch.delenv("AUTOJOB_SELF_HEAL_OPENCODE", raising=False)
    monkeypatch.setattr("scripts.self_heal_repair.shutil.which", lambda _name: None)
    with pytest.raises(FileNotFoundError, match="AUTOJOB_SELF_HEAL_OPENCODE"):
        resolve_opencode()


def test_resolve_model_defaults_to_deepseek(monkeypatch) -> None:
    monkeypatch.delenv("AUTOJOB_SELF_HEAL_REPAIR_MODEL", raising=False)
    monkeypatch.delenv("AUTOJOB_LLM_MODEL", raising=False)
    assert DEFAULT_REPAIR_MODEL == "deepseek/deepseek-v4.1-flash-1017"
    assert resolve_model() == "openrouter/deepseek/deepseek-v4.1-flash-1017"


def test_resolve_model_ignores_the_general_model(monkeypatch) -> None:
    """Task 14: AUTOJOB_LLM_MODEL is the general model, never the repair fallback."""
    monkeypatch.delenv("AUTOJOB_SELF_HEAL_REPAIR_MODEL", raising=False)
    monkeypatch.setenv("AUTOJOB_LLM_MODEL", "xiaomi/mimo-v2.6-pro")
    assert resolve_model() == "openrouter/deepseek/deepseek-v4.1-flash-1017"


def test_resolve_model_normalizes_the_bare_default(monkeypatch) -> None:
    """The Python settings inject the bare id; OpenCode needs the provider prefix."""
    monkeypatch.setenv("AUTOJOB_SELF_HEAL_REPAIR_MODEL", DEFAULT_REPAIR_MODEL)
    assert resolve_model() == "openrouter/deepseek/deepseek-v4.1-flash-1017"


def test_resolve_model_keeps_an_already_qualified_provider(monkeypatch) -> None:
    monkeypatch.setenv("AUTOJOB_SELF_HEAL_REPAIR_MODEL", "openrouter/deepseek/custom")
    assert resolve_model() == "openrouter/deepseek/custom"


def test_resolve_model_honors_an_explicit_override_verbatim(monkeypatch) -> None:
    monkeypatch.setenv("AUTOJOB_SELF_HEAL_REPAIR_MODEL", "other/provider")
    monkeypatch.setenv("AUTOJOB_LLM_MODEL", "xiaomi/mimo-v2.6-pro")
    assert resolve_model() == "other/provider"


def test_main_uses_the_self_healing_model_by_default(monkeypatch, bundle: Path) -> None:
    _set_loop_env(monkeypatch, bundle)
    monkeypatch.delenv("AUTOJOB_SELF_HEAL_REPAIR_MODEL", raising=False)
    monkeypatch.setenv("AUTOJOB_LLM_MODEL", "xiaomi/mimo-v2.6-pro")
    captured: dict = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = list(argv)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("scripts.self_heal_repair.subprocess.run", fake_run)

    assert main() == 0
    argv = captured["argv"]
    assert argv[argv.index("--model") + 1] == "openrouter/deepseek/deepseek-v4.1-flash-1017"


def test_main_builds_the_opencode_argv(monkeypatch, bundle: Path, capsys) -> None:
    report = _set_loop_env(monkeypatch, bundle)
    monkeypatch.setenv("AUTOJOB_SELF_HEAL_REPAIR_STANDALONE", "true")
    monkeypatch.setenv("AUTOJOB_SELF_HEAL_REPAIR_MODEL", "provider/model")
    monkeypatch.setenv("AUTOJOB_SELF_HEAL_REPAIR_AGENT", "build")
    captured: dict = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = list(argv)
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("scripts.self_heal_repair.subprocess.run", fake_run)

    assert main() == 0
    argv = captured["argv"]
    assert argv[0] == str(bundle / "fake-opencode")
    assert argv[1:3] == ["run", "--auto"]
    assert "--standalone" in argv
    assert argv[argv.index("--model") + 1] == "provider/model"
    assert argv[argv.index("--agent") + 1] == "build"
    assert argv[argv.index("--file") + 1] == str(report)
    # The incremental-implementation skill is attached alongside the report.
    assert str(SKILL_FILE) in argv
    # The prompt is positional and mentions the bug the bundle recorded.
    assert "BUG-099" in argv[-1]
    # The wrapper passes argv to the OS; it must never route the prompt through a shell.
    assert captured["kwargs"].get("shell", False) is False
    # The repair log names the resolved self-healing model explicitly.
    assert "self-healing model provider/model" in capsys.readouterr().out


def test_main_propagates_the_opencode_exit_code(monkeypatch, bundle: Path) -> None:
    _set_loop_env(monkeypatch, bundle)
    monkeypatch.setattr(
        "scripts.self_heal_repair.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=7),
    )
    assert main() == 7


def test_main_requires_the_evidence_report(monkeypatch, bundle: Path) -> None:
    _set_loop_env(monkeypatch, bundle, report=bundle / "missing.md")
    monkeypatch.setattr(
        "scripts.self_heal_repair.subprocess.run",
        lambda *_args, **_kwargs: pytest.fail("the agent must not launch without a report"),
    )
    assert main() == 2
