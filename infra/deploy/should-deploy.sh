#!/usr/bin/env bash
# Решение автодеплоя: выкладывать ли <тег> поверх <current> (current_tag на VPS 1). Запуск из git-клона с полной историей
# (checkout fetch-depth: 0): bash infra/deploy/should-deploy.sh <тег> <current>
# Печатает ровно одно слово и завершается с кодом 0:
#   deploy          current пуст (первая выкладка) или <тег> — потомок current: выкладывать
#   skip-same       <тег> и есть current: уже выложен
#   skip-older      <тег> — предок current: выложен более новый релиз, откатывать автодеплоем нельзя (инцидент 2026-10-28)
#   skip-diverged   <тег> и current не в отношении предок/потомок, либо current не удаётся разобрать (нет коммита в клоне,
#                   не sha): без ручного запуска не выкладываем
# Код 2 — ошибка вызова (нет аргументов, <тег> не коммит). Подробности — docs/runbooks/deploy.md.
set -euo pipefail

[ "$#" -eq 2 ] || { echo "usage: should-deploy.sh <tag> <current>" >&2; exit 2; }
tag="$1"
cur="$2"

tag_full="$(git rev-parse --verify -q "${tag}^{commit}")" || { echo "should-deploy: $tag не коммит этого клона" >&2; exit 2; }

if [ -z "$cur" ]; then
  echo deploy
  exit 0
fi

# current приходит с сервера: только hex-sha (не опция git и не ref) и только коммит, который есть в клоне
if ! [[ "$cur" =~ ^[0-9a-f]{7,64}$ ]] || ! cur_full="$(git rev-parse --verify -q "${cur}^{commit}")"; then
  echo skip-diverged
  exit 0
fi

if [ "$tag_full" = "$cur_full" ]; then
  echo skip-same
elif git merge-base --is-ancestor "$tag_full" "$cur_full"; then
  echo skip-older
elif git merge-base --is-ancestor "$cur_full" "$tag_full"; then
  echo deploy
else
  echo skip-diverged
fi
