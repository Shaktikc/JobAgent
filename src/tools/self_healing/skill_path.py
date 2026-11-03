"""Resolve the repair skill from the current layout or a legacy checkout."""

from pathlib import Path


def repair_skill_path(root: Path) -> Path:
    candidates = [root / folder / "skills" / "incremental-implementation" / "SKILL.md"
                  for folder in (".agents", ".opencode")]
    return next((path for path in candidates if path.is_file()), candidates[0])
