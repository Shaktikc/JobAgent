"""The repair wrapper must attach the skill after the .agents migration."""

from src.tools.self_healing.skill_path import repair_skill_path


def test_current_layout_wins_with_legacy_fallback(tmp_path):
    legacy = tmp_path / ".opencode/skills/incremental-implementation/SKILL.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy", encoding="utf-8")
    assert repair_skill_path(tmp_path) == legacy
    current = tmp_path / ".agents/skills/incremental-implementation/SKILL.md"
    current.parent.mkdir(parents=True)
    current.write_text("current", encoding="utf-8")
    assert repair_skill_path(tmp_path) == current
