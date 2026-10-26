#!/usr/bin/env bash
# Одна волна пункта 4: 25 параллельных публикаций CRM (лиды, старт по барьеру) + 25 параллельных публикаций ERP (потоки по барьеру) + 8 писем EDS.
D="$(cd "$(dirname "$0")" && pwd)"
( "$D/run.sh" crm_gen.py 1 25 0.0 2>&1 | tail -1 ) &
( docker exec -i -e GEN_K=25 rt-w11c-erp-backend-1 python manage.py shell < "$D/erp_par.py" 2>&1 | tail -1 ) &
( "$D/run.sh" eds_gen.py 8 0.3 2>&1 | tail -1 ) &
wait
