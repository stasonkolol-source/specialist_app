"""Check the step overview table of docs/DEVELOPMENT_PLAN.md (§4).

Verifies that every dependency exists, there are no cycles, dependencies point to
steps earlier in the table, and the gates 3.4, 6.7 and 8.5 transitively depend on
their mandatory steps. Exit code 1 on any failure.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PLAN = Path(__file__).resolve().parent.parent / "docs" / "DEVELOPMENT_PLAN.md"
STEP_RE = re.compile(r"\d+\.\d+[a-z]?")
ROW_RE = re.compile(r"^\| \d+\.\d+[a-z]? \|")
OPTIONAL = {"0.28", "7.6"}
GATE_34_REQUIRED = ["2.5b", "2.10", "2.11", "2.12", "3.2", "3.3", "1.7"]


def parse(text: str) -> tuple[list[str], dict[str, list[str]], dict[str, str]]:
    try:
        section = text.split("## 4. Обзор шагов")[1].split("\n---")[0]
    except IndexError:
        sys.exit("plan-check: section «## 4. Обзор шагов» not found")
    order: list[str] = []
    deps: dict[str, list[str]] = {}
    status: dict[str, str] = {}
    for line in section.splitlines():
        if not ROW_RE.match(line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        step, dep_cell = cells[0], cells[2]
        main = dep_cell.split("‖")[0]
        order.append(step)
        deps[step] = [] if main.strip() == "—" else STEP_RE.findall(main)
        status[step] = cells[-1]
    return order, deps, status


def closure(step: str, deps: dict[str, list[str]]) -> set[str]:
    seen: set[str] = set()
    stack = list(deps.get(step, []))
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(deps.get(cur, []))
    return seen


def main() -> int:
    order, deps, status = parse(PLAN.read_text(encoding="utf-8"))
    idx = {s: i for i, s in enumerate(order)}
    errors: list[str] = []
    for step, ds in deps.items():
        for d in ds:
            if d not in idx:
                errors.append(f"{step}: dependency {d} does not exist")
            elif idx[d] > idx[step]:
                errors.append(f"{step}: dependency {d} is listed later in the table")
    for step in order:
        if step in closure(step, deps):
            errors.append(f"{step}: dependency cycle")
    for gate in ("8.5", "6.7"):
        if gate not in idx:
            errors.append(f"gate {gate} missing")
            continue
        reach = closure(gate, deps) | {gate}
        missing = [
            s for s in order if idx[s] < idx[gate] and s not in reach and s not in OPTIONAL
        ]
        if missing:
            errors.append(f"gate {gate} does not depend on: {', '.join(missing)}")
    if "3.4" in idx:
        reach34 = closure("3.4", deps)
        lacking = [s for s in GATE_34_REQUIRED if s not in reach34]
        if lacking:
            errors.append(f"gate 3.4 does not depend on: {', '.join(lacking)}")
    done = sum(1 for s in order if status.get(s) == "принят")
    print(f"plan-check: {len(order)} steps, accepted {done}")
    for e in errors:
        print(f"  FAIL {e}")
    if errors:
        return 1
    print("plan-check: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
