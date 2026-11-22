"""Use the existing installer catalog as the sole source of Skill pins."""

from scripts.install import load_catalog

ROLES = {
    "strategy": "global-gtm-strategy-skill",
    "content": "global-growth-content",
}


def skill_registry():
    catalog = {item["skill"]: item for item in load_catalog()}
    return {
        stage: {"skill_id": skill, **{
            key: catalog[skill][key] for key in ("revision", "repository", "path")
        }}
        for stage, skill in ROLES.items()
    }
