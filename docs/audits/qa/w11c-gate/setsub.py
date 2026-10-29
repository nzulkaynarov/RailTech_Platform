#!/usr/bin/env python3
"""SUBS_FILE=<файл> setsub.py <имя> [enabled=true|false] [drop=true|false|-] — правит блок подписчика в subscriptions.yaml НА МЕСТЕ (тот же inode)"""
import re, sys, os
P = os.environ["SUBS_FILE"]   # копия subscriptions.yaml вне репозитория (bind-mount на /opt/rt/contracts/bus)
name = sys.argv[1]
opts = dict(a.split("=") for a in sys.argv[2:])
src = open(P).read()
lines = src.split("\n")
out, i = [], 0
while i < len(lines):
    l = lines[i]
    if l.strip() == f"- name: {name}":
        out.append(l); i += 1
        while i < len(lines) and lines[i].startswith("    ") and not lines[i].strip().startswith("enabled:") and not lines[i].strip().startswith("drop:"):
            out.append(lines[i]); i += 1
        while i < len(lines) and (lines[i].strip().startswith("enabled:") or lines[i].strip().startswith("drop:")):
            i += 1
        if "enabled" in opts: out.append(f"    enabled: {opts['enabled']}")
        if opts.get("drop", "-") != "-": out.append(f"    drop: {opts['drop']}")
        continue
    out.append(l); i += 1
with open(P, "r+") as f:   # на месте: bind-mount привязан к inode
    f.seek(0); f.write("\n".join(out)); f.truncate()
print(f"{name}: {opts}")
