"""The 13 catalog edits that pin the gate of SPR-03 to the gate of 3cc1bd3 (TK1 fix round 1, review point 1).

`tests/fixtures/gate/evals/` is a frozen copy of the catalog, the two `cases.json` and the six compact evidence files committed at TK1.
`tests/fixtures/gate/golden.json` holds, for each edit below, the set of problem lines the OLD gate (`git archive 3cc1bd3`, reading the raw
`runs/<batch>/` folders) printed, with `runs/<batch>` spelled `EVID(<evals folder>,<batch>)`. The new gate must print exactly that set for the same
edit over the compact files, spelled the same way. The generator that wrote golden.json imported this module (see evidence/tk1.txt of SPR-03).
"""
from __future__ import annotations

import copy
import re
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "gate"
GOLDEN = FIXTURE / "golden.json"
DQA, SCS = "data-quality-audit", "skill-creator-studio"


def edit(name, targets=None, **changes):
    """Edit the catalog entry `name`: `targets`, plain keys, and `ev_<key>` for a key of its `evaluated` block."""
    def apply(catalog):
        for skill in catalog["skills"]:
            if skill["name"] == name:
                if targets:
                    skill["targets"] = targets
                for key, value in changes.items():
                    if key.startswith("ev_"):
                        skill.setdefault("evaluated", {})[key[3:]] = value
                    else:
                        skill[key] = value
    return apply


NOT_RUN = {"claude-code": "not_run:a", "codex": "not_run:b", "antigravity": "not_run:c"}
TRUE = {"model_evaluated": True, "status": "model-evaluated"}
MUTATIONS = [
    ("as committed", lambda c: None),
    ("dqa flag true", edit(DQA, **TRUE)),
    ("scs flag true (no evaluated block)", edit(SCS, **TRUE)),
    ("dqa sprint SPR-33", edit(DQA, ev_sprint="SPR-33")),
    ("dqa sprint studio-SPR-02 flag true", edit(DQA, ev_sprint="studio-SPR-02", ev_result="passed", **TRUE)),
    ("dqa codex not_run", edit(DQA, ev_harnesses={"claude-code": "ran", "codex": "not_run:x", "antigravity": "not_run:y"})),
    ("dqa targets claude-code only", edit(DQA, targets=["claude-code"])),
    ("scs targets claude-code only", edit(SCS, targets=["claude-code"])),
    ("dqa result passed flag false", edit(DQA, ev_result="passed")),
    ("dqa result partial", edit(DQA, ev_result="partial")),
    ("dqa date other", edit(DQA, ev_date="2026-10-19")),
    ("dqa all not_run", edit(DQA, ev_harnesses=NOT_RUN, ev_result="not_run")),
    ("dqa flag true every harness", edit(DQA, ev_sprint="SPR-18", ev_result="passed", **TRUE)),
]


def new_catalog(base: dict, mutate) -> dict:
    """The edited catalog in the new layout: `evidence` and `ab_report` follow the sprint the edit chose."""
    catalog = copy.deepcopy(base)
    mutate(catalog)
    for skill in catalog["skills"]:
        if "evaluated" in skill:
            skill["evaluated"]["evidence"] = "evals/%s/evidence/%s.json" % (skill["name"], skill["evaluated"]["sprint"])
            skill["evaluated"]["ab_report"] = skill["evaluated"]["evidence"]
    return catalog


def old_catalog(catalog: dict) -> dict:
    """The same edit in the layout of 3cc1bd3: no `evidence` key, `ab_report` points into runs/<sprint>/."""
    old = copy.deepcopy(catalog)
    for skill in old["skills"]:
        if "evaluated" in skill:
            skill["evaluated"].pop("evidence", None)
            skill["evaluated"]["ab_report"] = "evals/%s/runs/%s/ab-2026-10-18.md" % (skill["name"], skill["evaluated"]["sprint"])
    return old


def norm_old(text: str) -> str:
    return re.sub(r"\S*evals/([\w-]+)/runs/([\w-]+)", r"EVID(\1,\2)", text)


def norm_new(text: str) -> str:
    text = re.sub(r"evals/([\w-]+)/evidence/([\w-]+)\.json", r"EVID(\1,\2)", text)
    return re.sub(r"log ([\w-]+)/(smoke/)?", "log ", text)
