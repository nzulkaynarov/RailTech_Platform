#!/usr/bin/env bash
# Проверка на ЖИВОМ стенде (S0-9): ключи S3 на сервис разграничивают доступ. Независимый клиент (curl SigV4 из образа RustFS),
# не тот rc, которым s3-init проверяет себя сам. Не входит в `make deploy-check` (нужен поднятый стенд).
#   infra/deploy/tests/s3-keys-live-test.sh <проект compose> <env-файл>
# Условия: в проекте работают rustfs и s3-init (`docker compose -p <проект> … up -d rustfs s3-init`), env-файл тот же, что у стенда.
# Проверяется: ключом ERP нельзя читать wal и бакеты CRM, ключом CRM — бакеты ERP и wal, у CRM backups только на чтение,
# WAL-G видит только wal, бэкап — только backups, анонимный доступ закрыт; свои бакеты читаются и пишутся. Секреты не печатаются.
set -euo pipefail
project="${1:?usage: s3-keys-live-test.sh <проект compose> <env-файл>}"
envfile="${2:?usage: s3-keys-live-test.sh <проект compose> <env-файл>}"
net="${project}_default"
docker network inspect "$net" >/dev/null 2>&1 || { echo "нет сети $net — стенд проекта $project не поднят"; exit 1; }

# Значения читаем из файла, а не через `source`: в нём могут быть пробелы, а переменные оболочки перебили бы env-файл у compose.
val() { grep -E "^$1=" "$envfile" | head -n1 | cut -d= -f2-; }
envs=()
for n in ROOT ERP CRM LANGFUSE WAL BACKUP; do
  for p in ACCESS SECRET; do envs+=(-e "S3_${n}_${p}_KEY=$(val "S3_${n}_${p}_KEY")"); done
done

docker run --rm --network "$net" --platform linux/amd64 "${envs[@]}" --entrypoint sh rustfs/rustfs:1.0.1 -c '
ep=http://rustfs:9000
code() { # <ключ> <метод> <путь> [тело]
  ak=$(eval echo "\$S3_$1_ACCESS_KEY"); sk=$(eval echo "\$S3_$1_SECRET_KEY")
  curl -s -o /dev/null -w "%{http_code}" --aws-sigv4 "aws:amz:us-east-1:s3" --user "$ak:$sk" -X "$2" ${4:+--data-binary "$4"} "$ep/$3"
}
fails=0
expect() { # <ok|deny> <описание> <код>
  case "$1:$3" in ok:2*|deny:403) printf "  ok   %-46s %s\n" "$2" "$3" ;; *) printf "  FAIL %-46s %s\n" "$2" "$3"; fails=$((fails+1)) ;; esac
}
list() { code "$1" GET "$2?list-type=2"; }
for b in erp-private erp-public erp-temp; do expect ok "ERP читает $b" "$(list ERP $b)"; done
for b in wal backups kb-sources client-documents tg-attachments langfuse; do expect deny "ERP не читает $b" "$(list ERP $b)"; done
expect ok "ERP пишет и удаляет в erp-private" "$(code ERP PUT erp-private/.live-probe x)"; code ERP DELETE erp-private/.live-probe >/dev/null
expect deny "ERP не пишет в wal" "$(code ERP PUT wal/.live-probe x)"
for b in kb-sources client-documents tg-attachments; do expect ok "CRM читает $b" "$(list CRM $b)"; done
expect ok "CRM пишет и удаляет в kb-sources" "$(code CRM PUT kb-sources/.live-probe x)"; code CRM DELETE kb-sources/.live-probe >/dev/null
for b in erp-private erp-public erp-temp wal langfuse; do expect deny "CRM не читает $b" "$(list CRM $b)"; done
expect ok "CRM читает backups" "$(list CRM backups)"
expect deny "CRM не пишет в backups" "$(code CRM PUT backups/.live-probe x)"
expect ok "WAL-G читает и пишет wal" "$(list WAL wal)"; expect ok "WAL-G пишет в wal" "$(code WAL PUT wal/.live-probe x)"; code WAL DELETE wal/.live-probe >/dev/null
for b in erp-private backups langfuse kb-sources; do expect deny "WAL-G не читает $b" "$(list WAL $b)"; done
expect ok "бэкап читает backups" "$(list BACKUP backups)"; expect ok "бэкап пишет в backups" "$(code BACKUP PUT backups/.live-probe x)"; code BACKUP DELETE backups/.live-probe >/dev/null
for b in wal erp-private kb-sources; do expect deny "бэкап не читает $b" "$(list BACKUP $b)"; done
expect ok "Langfuse читает langfuse" "$(list LANGFUSE langfuse)"
expect deny "Langfuse не читает erp-private" "$(list LANGFUSE erp-private)"
expect deny "аноним не читает erp-public" "$(curl -s -o /dev/null -w "%{http_code}" "$ep/erp-public?list-type=2")"
echo "ошибок: $fails"
[ "$fails" -eq 0 ]
' 2>&1 | grep -v "^WARNING"
echo "s3-keys-live-test: ok"
