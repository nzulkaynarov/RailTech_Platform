#!/usr/bin/env python3
"""Тест графа jobs .github/workflows/deploy.yml (ВЫКЛ-3): какие jobs запускаются на каждое событие.

26.11-27.11 ручной запуск «успешно» завершился при пропущенном job deploy (GitHub пропускает job, если пропущен job выше по цепочке
needs, а явного `if` нет), и проверить это было нечем. Тест разбирает deploy.yml, считает job-level `if` и `needs` по семантике GitHub
Actions (подмножество выражений: контексты github/inputs/needs, ==, !=, &&, ||, !, cancelled(), always(), success(), failure())
и сверяет набор запущенных jobs с ожидаемым. Исход jobs в модели - success, кроме явно заданных в сценарии.
Запуск: python3 infra/deploy/tests/deploy-jobgraph-test.py [путь/к/deploy.yml]
"""
import re
import sys
from pathlib import Path

import yaml

WORKFLOW = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[3] / ".github/workflows/deploy.yml"

TOKEN = re.compile(r"\s*(?:(&&|\|\||==|!=|!|\(|\)|,)|'((?:[^']|'')*)'|([A-Za-z_][\w.\-]*)|(\d+))")


def tokenize(src):
    pos, out = 0, []
    src = src.strip()
    while pos < len(src):
        m = TOKEN.match(src, pos)
        if not m:
            raise ValueError(f"не разобрать выражение: {src!r} с позиции {pos}")
        op, string, ident, num = m.groups()
        if op:
            out.append(("op", op))
        elif string is not None:
            out.append(("str", string.replace("''", "'")))
        elif ident:
            out.append(("id", ident))
        else:
            out.append(("str", num))
        pos = m.end()
    return out


class Evaluator:
    def __init__(self, src, ctx, status):
        self.t, self.i, self.ctx, self.status = tokenize(src), 0, ctx, status

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self):
        tok = self.t[self.i]
        self.i += 1
        return tok

    def parse(self):
        v = self.or_()
        if self.i != len(self.t):
            raise ValueError(f"лишние токены в выражении: {self.t[self.i:]}")
        return v

    def or_(self):
        v = self.and_()
        while self.peek() == ("op", "||"):
            self.take()
            r = self.and_()
            v = v if truthy(v) else r
        return v

    def and_(self):
        v = self.eq()
        while self.peek() == ("op", "&&"):
            self.take()
            r = self.eq()
            v = r if truthy(v) else v
        return v

    def eq(self):
        v = self.unary()
        while self.peek() in (("op", "=="), ("op", "!=")):
            op = self.take()[1]
            r = self.unary()
            same = str(v).lower() == str(r).lower()
            v = same if op == "==" else not same
        return v

    def unary(self):
        if self.peek() == ("op", "!"):
            self.take()
            return not truthy(self.unary())
        return self.atom()

    def atom(self):
        kind, val = self.take()
        if (kind, val) == ("op", "("):
            v = self.or_()
            assert self.take() == ("op", ")")
            return v
        if kind == "str":
            return val
        if kind == "id":
            if self.peek() == ("op", "("):  # вызов функции статуса
                self.take()
                assert self.take() == ("op", ")"), f"функция {val} с аргументами не поддерживается тестом"
                return self.status(val)
            if val in ("true", "false"):
                return val == "true"
            return self.ctx(val)
        raise ValueError(f"неожиданный токен {kind} {val}")


def truthy(v):
    return bool(v) and v not in ("", "0")


STATUS_FUNCS = re.compile(r"\b(always|cancelled|success|failure)\s*\(")


def run_graph(wf, event, inputs=None, schedule="", outputs=None, results=None):
    """Возвращает {job: 'success'|'skipped'|...}. outputs - {job: {имя: значение}}; results - заданный исход запущенного job."""
    inputs, outputs, results = inputs or {}, outputs or {}, results or {}
    jobs = wf["jobs"]
    state, out = {}, {}

    def order(name, seen=()):
        for n in as_list(jobs[name].get("needs")):
            if n not in state:
                order(n, seen + (name,))
        if name not in state:
            evaluate(name)

    def ancestors(name):
        found = set()
        stack = list(as_list(jobs[name].get("needs")))
        while stack:
            n = stack.pop()
            if n not in found:
                found.add(n)
                stack.extend(as_list(jobs[n].get("needs")))
        return found

    def evaluate(name):
        job = jobs[name]
        needs = as_list(job.get("needs"))
        need_res = {n: state[n] for n in needs}
        # Неявный success()/failure() в GitHub смотрит всех предков по цепочке needs, не только прямые: пропущенный gate
        # пропускает и build без своего `if`, хотя его прямой needs (prepare) успешен (регрессия #956).
        anc_res = {a: state[a] for a in ancestors(name)}
        all_ok = all(r == "success" for r in anc_res.values())
        any_failed = any(r == "failure" for r in anc_res.values())

        def ctx(path):
            parts = path.split(".")
            if path == "github.event_name":
                return event
            if path == "github.event.schedule":
                return schedule
            if parts[0] == "inputs":
                return inputs.get(parts[1], "")
            if parts[0] == "needs":
                if parts[2] == "result":
                    return need_res.get(parts[1], "")
                if parts[2] == "outputs":
                    return out.get(parts[1], {}).get(parts[3], "")
            if parts[0] == "vars" or parts[0] == "secrets":
                return ""
            raise KeyError(f"контекст {path} в if job {name} тест не знает")

        def status(fn):
            return {"always": True, "cancelled": False, "success": all_ok, "failure": any_failed}[fn]

        cond = job.get("if")
        if cond is None:
            run = all_ok
        else:
            src = str(cond).strip()
            m = re.fullmatch(r"\$\{\{(.*)\}\}", src, re.S)
            src = m.group(1) if m else src
            res = truthy(Evaluator(src, ctx, status).parse())
            run = res if STATUS_FUNCS.search(src) else (all_ok and res)
        state[name] = results.get(name, "success") if run else "skipped"
        if run:
            out[name] = dict(outputs.get(name, {}))
            if name == "prepare":
                out[name].setdefault("action", "deploy" if event == "schedule" else inputs.get("action", ""))
            if name == "deploy":  # штатная выкладка: на VPS 1 был прежний тег, выкладка не пропущена
                out[name].setdefault("previous", "0" * 40)
                out[name].setdefault("skip", "false")

    for n in jobs:
        order(n)
    return state


def as_list(v):
    return [] if v is None else v if isinstance(v, list) else [v]


NIGHT, DAY = "0 20 * * *", "*/15 1-17 * * *"
SCENARIOS = [
    # (название, event, inputs, schedule, outputs, results, ожидаемые запущенные jobs)
    ("ручной deploy после одобрения", "workflow_dispatch", {"action": "deploy"}, "", {}, {},
     {"prepare", "build", "approve", "deploy", "release-notes"}),
    ("ручной deploy, одобрение отклонено", "workflow_dispatch", {"action": "deploy"}, "", {}, {"approve": "failure"},
     {"prepare", "build", "approve"}),
    ("ручной rollback после одобрения", "workflow_dispatch", {"action": "rollback"}, "", {}, {},
     {"approve", "rollback"}),
    ("ручной rollback, одобрение отклонено", "workflow_dispatch", {"action": "rollback"}, "", {}, {"approve": "failure"},
     {"approve"}),
    ("ручной build (без выкладки)", "workflow_dispatch", {"action": "build"}, "", {}, {},
     {"prepare", "build"}),
    ("расписание, ночное окно: gate сказал go", "schedule", {}, NIGHT, {"gate": {"go": "true"}}, {},
     {"gate", "prepare", "build", "deploy", "release-notes", "banner-cleanup"}),
    ("расписание, день: никого нет - go", "schedule", {}, DAY, {"gate": {"go": "true"}}, {},
     {"gate", "prepare", "build", "deploy", "release-notes", "banner-cleanup"}),
    ("расписание, день: skip/wait/banner - go=false", "schedule", {}, DAY, {"gate": {"go": "false"}}, {},
     {"gate"}),
    ("расписание, ночной крон, но решение skip (нечего выкладывать)", "schedule", {}, NIGHT, {"gate": {"go": "false"}}, {},
     {"gate"}),
    ("крон баннера 00:30", "schedule", {}, "30 19 * * *", {}, {},
     {"notice"}),
    ("расписание go, но build упал", "schedule", {}, DAY, {"gate": {"go": "true"}}, {"build": "failure"},
     {"gate", "prepare", "build", "banner-cleanup"}),
]


def main():
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    bad = 0
    for title, event, inputs, schedule, outputs, results, expected in SCENARIOS:
        state = run_graph(wf, event, inputs, schedule, outputs, results)
        ran = {j for j, r in state.items() if r != "skipped"}
        if ran != expected:
            bad += 1
            print(f"FAIL: {title}\n  запущены:  {sorted(ran)}\n  ожидались: {sorted(expected)}")
        else:
            print(f"ok:   {title}")
    # прямые утверждения из задачи: deploy идёт для dispatch-deploy после approve и для schedule-go, и никогда - для skip
    for title, event, inputs, schedule, outputs, results, expected in SCENARIOS:
        state = run_graph(wf, event, inputs, schedule, outputs, results)
        if "go" in outputs.get("gate", {}) and outputs["gate"]["go"] == "false" and state["deploy"] != "skipped":
            bad += 1
            print(f"FAIL: deploy запущен при go=false ({title})")
    if bad:
        sys.exit(1)
    print("deploy-jobgraph-test: ok")


if __name__ == "__main__":
    main()
