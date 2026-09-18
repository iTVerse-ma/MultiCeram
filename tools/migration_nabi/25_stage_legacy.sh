#!/usr/bin/env bash
# M1 — copie des tables de mc2 utiles au chargeur 30_load_nabi19.py dans le schéma `legacy` de la base cible.
# Sans mots de passe ; seuls les paramètres zk.* sont gardés, mots de passe et jetons vidés.
# Base neuve uniquement : le schéma legacy (et sa table de correspondances itv_map) est recréé.
#
#   cd /srv/stacks/dev-docker && repos/MultiCeram/tools/migration_nabi/25_stage_legacy.sh [base]   # défaut multiceram_nabi
set -eo pipefail
DB=${1:-multiceram_nabi}
TABLES="zk_transaction zk_terminals x_jour_repos hr_employee resource_resource hr_department res_users res_partner res_company res_groups res_groups_users_rel ir_model_data hr_leave hr_leave_type hr_leave_allocation resource_calendar_leaves ir_config_parameter"
TARGS=$(for t in $TABLES; do printf -- '-t public.%s ' "$t"; done)

if docker exec dev-docker-db psql -U odoo -d "$DB" -tA -c "SELECT to_regclass('legacy.itv_map')" | grep -q itv_map && [ "${FORCE:-0}" != 1 ]; then
  echo "legacy.itv_map existe déjà dans $DB (reprise faite) : relancer avec FORCE=1 pour tout recréer" >&2
  exit 1
fi

# Le cron du serveur de dev se connecte à toute nouvelle base : suppression WITH (FORCE).
docker exec dev-docker-db psql -U odoo -d postgres -q -c "DROP DATABASE IF EXISTS mc2_stage_tmp WITH (FORCE)" -c "CREATE DATABASE mc2_stage_tmp"
docker exec multiceram-dbProd17-1 pg_dump -U odoo -d mc2 --no-owner --no-privileges --section=pre-data --section=data -Fc $TARGS \
  | docker exec -i dev-docker-db pg_restore -U odoo -d mc2_stage_tmp --no-owner --no-privileges
docker exec dev-docker-db psql -U odoo -d mc2_stage_tmp -v ON_ERROR_STOP=1 -q \
  -c "ALTER TABLE res_users DROP COLUMN IF EXISTS password" \
  -c "DELETE FROM ir_config_parameter WHERE key NOT LIKE 'zk.%'" \
  -c "UPDATE ir_config_parameter SET value = '' WHERE key ~ '(password|token)'" \
  -c "ALTER SCHEMA public RENAME TO legacy"
docker exec dev-docker-db psql -U odoo -d "$DB" -q -c "DROP SCHEMA IF EXISTS legacy CASCADE"
docker exec dev-docker-db sh -c "set -o pipefail; pg_dump -U odoo -d mc2_stage_tmp -n legacy -Fc | pg_restore -U odoo -d $DB --no-owner --no-privileges"
docker exec dev-docker-db psql -U odoo -d postgres -q -c "DROP DATABASE mc2_stage_tmp WITH (FORCE)"
docker exec dev-docker-db psql -U odoo -d "$DB" -tA -c "SELECT 'legacy : ' || count(*) || ' tables, ' || (SELECT count(*) FROM legacy.zk_transaction) || ' pointages' FROM information_schema.tables WHERE table_schema = 'legacy'"
