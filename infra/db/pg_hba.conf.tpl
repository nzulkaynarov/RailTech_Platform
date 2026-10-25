# pg_hba.conf сервера PostgreSQL на VPS 2. Шаблон: infra/deploy/db-up.sh подставляет @APP_INTERNAL_IP@ (внутренний IP VPS 1).
# Только TLS (hostssl), только SCRAM, у каждой роли — своя база; всё остальное запрещено.
# TYPE   DATABASE   USER          ADDRESS                  METHOD
local    all        postgres                               peer
hostssl  crm        crm_app       @APP_INTERNAL_IP@/32     scram-sha-256
hostssl  erp        erp_app       @APP_INTERNAL_IP@/32     scram-sha-256
hostssl  eds        eds_app       @APP_INTERNAL_IP@/32     scram-sha-256
hostssl  litellm    litellm_app   @APP_INTERNAL_IP@/32     scram-sha-256
hostssl  langfuse   langfuse_app  @APP_INTERNAL_IP@/32     scram-sha-256
# Контейнер backup (сеть compose); с наружи сюда пакеты не попадают — порт связан с внутренним IP, ufw закрывает остальное.
host     all        rt_backup     172.16.0.0/12            scram-sha-256
host     all        all           0.0.0.0/0                reject
host     all        all           ::/0                     reject
