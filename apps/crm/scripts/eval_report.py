#!/usr/bin/env python3
"""Сводка evals в Markdown для комментария к PR (job eval-gate).

Читает backend/evals/reports/{dialog,qualifier}.json и печатает таблицу метрик
с порогами SPEC §12 и списком проваленных кейсов.

Пример: scripts/eval_report.py backend/evals/reports > eval-report.md
"""

import argparse
import json
import sys
from pathlib import Path

TITLES = {
    "dialog": "Диалоговый агент (golden)",
    "qualifier": "Квалификатор и эскалации",
}
LOWER_IS_BETTER = {"invented_numbers"}


def section(name: str, data: dict) -> list[str]:
    lines = [
        f"### {TITLES.get(name, name)}",
        "",
        "| Метрика | Значение | Порог | |",
        "|---|---|---|---|",
    ]
    gates = data.get("gates", {})
    for key, value in data.get("metrics", {}).items():
        gate = gates.get(key)
        if key in LOWER_IS_BETTER:
            gate, ok = 0, value == 0
        else:
            ok = gate is None or (value is not None and value >= gate)
        lines.append(
            f"| {key} | {value} | {'' if gate is None else gate} | {'✅' if ok else '❌'} |"
        )
    failed = data.get("failed") or {}
    if failed:
        lines += [
            "",
            f"<details><summary>Проваленные кейсы: {len(failed)}</summary>",
            "",
        ]
        items = failed.items() if isinstance(failed, dict) else ((f, "") for f in failed)
        lines += [f"- `{case}` {', '.join(why) if why else ''}" for case, why in items]
        lines += ["", "</details>"]
    return [*lines, ""]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("reports", type=Path, help="каталог с dialog.json / qualifier.json")
    args = parser.parse_args()
    files = sorted(args.reports.glob("*.json"))
    if not files:
        sys.stderr.write(f"Нет отчётов в {args.reports}. Сначала запустите make eval.\n")
        return 1
    sha = ""
    out = ["## Eval-gate", ""]
    for path in files:
        data = json.loads(path.read_text("utf-8"))
        sha = data.get("git_sha", sha)
        out += section(path.stem, data)
    out.append(f"_git sha: `{sha}` · пороги — SPEC §12_")
    sys.stdout.write("\n".join(out) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
