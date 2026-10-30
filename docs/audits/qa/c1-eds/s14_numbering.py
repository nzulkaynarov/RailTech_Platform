"""Пункт 8: 50 параллельных созданий служебных записок (СЗ, 5 авторов) и 50 входящих писем (ВХ, директор) -> номера подряд без пропусков и дублей."""
import concurrent.futures as cf
import re
import threading

from c1lib import *

N = 50
st = load()
authors = ["manager", "supply", "engineer", "mgr_acc", "director"]
tok = {k: eds_token(crm_token(st, k))[0] for k in authors}
b1, b2 = threading.Barrier(N), threading.Barrier(N)


def memo(i):
    b1.wait()
    k = authors[i % 5]
    t0 = time.time()
    c, b, _ = eds("POST", "/api/v1/documents", tok[k], {"kind": "memo", "subject": f"Нумерация {i}", "text": "параллельный тест"}, headers={"Idempotency-Key": f"c1-num-memo-{i}-{int(t0)}"})
    return c, (b.get("number") if isinstance(b, dict) else None), time.time() - t0


def letter(i):
    b2.wait()
    t0 = time.time()
    c, b, _ = eds("POST", "/api/v1/letters", tok["director"], {"subject": f"Письмо {i}", "summary": "параллельный тест", "sender": {"name": f"Отправитель {i}", "inn": None}, "received_at": "2026-10-26"}, headers={"Idempotency-Key": f"c1-num-let-{i}-{int(t0)}"})
    return c, (b.get("number") if isinstance(b, dict) else None), time.time() - t0


def run(fn, label, pattern):
    t0 = time.time()
    with cf.ThreadPoolExecutor(N) as ex:
        res = list(ex.map(fn, range(N)))
    wall = time.time() - t0
    codes = {}
    for c, _, _ in res:
        codes[c] = codes.get(c, 0) + 1
    nums = sorted(n for c, n, _ in res if n)
    seqs = [int(re.search(pattern, n).group(1)) for n in nums]
    lo, hi = min(seqs), max(seqs)
    dup = len(seqs) - len(set(seqs))
    gaps = sorted(set(range(lo, hi + 1)) - set(seqs))
    lat = sorted(d for _, _, d in res)
    print(f"[{label}] статусы {codes}; создано {len(nums)}; диапазон {nums[0]} .. {nums[-1]}; дубли {dup}; пропуски {gaps or 'нет'}; wall {wall:.2f}s; латентность p50 {lat[N//2]:.2f}s max {lat[-1]:.2f}s")
    print("   отсортированный список:", ", ".join(nums))
    return nums


m = run(memo, "СЗ", r"/(\d+)$")
l = run(letter, "ВХ", r"-(\d+)/")
