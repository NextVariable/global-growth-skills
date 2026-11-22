"""Select a subset of roles and bind edges only between selected stages."""

from .contracts import HarnessError
from .registry import ROLES

DEFAULT = ("strategy", "content")
PARENTS = {
    "strategy": (),
    "content": ("strategy",),
    "launch": ("content", "strategy"),
    "sales": ("strategy", "content"),
    "experiments": ("strategy", "content", "launch", "sales"),
}
HANDOFF_KINDS = {
    "launch": ("positioning", "capabilities"),
    "sales": ("positioning", "pricing", "capabilities"),
    "experiments": ("positioning", "launch-plan", "sales-plan"),
}
OUTPUTS = {"launch": "launch-plan", "sales": "sales-plan", "experiments": "experiment-plan"}
ALIASES = {
    "strategy": ("strategy", "market", "战略", "市场"),
    "content": ("content", "copy", "内容", "文案"),
    "launch": ("launch", "acquisition", "channel", "获客", "渠道", "发布"),
    "sales": ("sales", "retention", "销售", "留存", "续费"),
    "experiments": ("experiment", "实验", "复盘"),
}


def plan(stages=None, goal=None):
    if stages is None and goal:
        lower = goal.casefold()
        stages = list(ROLES) if any(s in lower for s in ("full workflow", "完整", "全链路")) else [
            role for role, aliases in ALIASES.items() if any(alias in lower for alias in aliases)
        ]
        if not stages:
            raise HarnessError("goal did not select a stage; specify --stages explicitly")
    if stages is None:
        stages = DEFAULT
    if not stages or len(set(stages)) != len(stages) or set(stages) - ROLES.keys():
        raise HarnessError("select unique, known stages")
    return list(stage for stage in ROLES if stage in stages)
