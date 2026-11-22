"""Prepare the same fixed Git objects the standalone installer uses."""

from pathlib import Path
import subprocess

from scripts.install import fetch

from .codex_host import skill_documents
from .contracts import HarnessError, ROOT
from .registry import skill_registry


def prepare_pins(directory):
    root = Path(directory).resolve()
    if root.is_relative_to(ROOT) or any((p / ".git").exists() for p in (root, *root.parents)):
        raise HarnessError("use a new Skill checkout directory outside Git")
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    for stage, pin in skill_registry().items():
        try:
            fetch(pin, root / stage)
            skill_documents(root / stage, pin)
        except (subprocess.SubprocessError, ValueError) as exc:
            raise HarnessError(
                f"could not prepare {stage} pin; inspect network and retry in a new directory"
            ) from exc
    return {"status": "prepared", "stages": list(skill_registry())}
