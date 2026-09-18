#!/usr/bin/env bash
# Préparation de la copie intégrale 40_full_copy_mc2.py :
# 1. copie complète de mc2 dans le schéma `mc2` de la base cible (via une base temporaire) ;
# 2. mots de passe, jetons et secrets vidés dans ce schéma (le serveur de dev est sur un port public) ;
# 3. fichiers des images de contacts / employés et des pièces jointes de messages copiés dans le filestore cible.
#
#   cd /srv/stacks/dev-docker && repos/MultiCeram/tools/migration_nabi/35_stage_mc2_schema.sh [base]   # défaut multiceram_nabi
set -eo pipefail
DB=${1:-multiceram_nabi}
MC2_ODOO=multiceram-odoo15-1   # conteneur Odoo 18 qui porte le filestore de mc2

echo "=== 1. schéma mc2 ==="
docker exec dev-docker-db psql -U odoo -d postgres -tA -c "DROP DATABASE IF EXISTS mc2_stage WITH (FORCE)" -c "CREATE DATABASE mc2_stage"
# pg_restore signale quelques erreurs sans conséquence (extensions, droits) : on ne s'arrête pas dessus.
docker exec multiceram-dbProd17-1 pg_dump -U odoo -Fc --no-owner --no-acl mc2 \
  | docker exec -i dev-docker-db pg_restore -U odoo -d mc2_stage --no-owner --no-acl 2>&1 | tail -2 || true
docker exec dev-docker-db psql -U odoo -d mc2_stage -tA -c "ALTER SCHEMA public RENAME TO mc2" -c "CREATE SCHEMA public"
docker exec dev-docker-db psql -U odoo -d "$DB" -tA -c "DROP SCHEMA IF EXISTS mc2 CASCADE"
docker exec dev-docker-db sh -c "pg_dump -U odoo -Fc --no-owner -n mc2 mc2_stage | pg_restore -U odoo -d $DB --no-owner" 2>&1 | tail -2 || true
docker exec dev-docker-db psql -U odoo -d postgres -tA -c "DROP DATABASE mc2_stage WITH (FORCE)"

echo "=== 2. secrets vidés dans le schéma mc2 ==="
docker exec -i dev-docker-db psql -U odoo -d "$DB" -tA <<'SQL'
UPDATE mc2.res_users SET password = NULL WHERE password IS NOT NULL;
UPDATE mc2.ir_config_parameter SET value = '' WHERE key ~* '(password|token|secret)';
UPDATE mc2.iap_account SET account_token = '' WHERE account_token IS NOT NULL;
SELECT 'schéma mc2 : ' || (SELECT count(*) FROM information_schema.tables WHERE table_schema = 'mc2') || ' tables, '
    || (SELECT count(*) FROM mc2.zk_transaction) || ' pointages, secrets restants : '
    || (SELECT count(*) FROM mc2.res_users WHERE password IS NOT NULL) + (SELECT count(*) FROM mc2.ir_config_parameter WHERE key ~* '(password|token|secret)' AND value <> '');
SQL

echo "=== 3. fichiers du filestore ==="
LIST=$(mktemp)
docker exec multiceram-dbProd17-1 psql -U odoo -d mc2 -tA -c "SELECT DISTINCT store_fname FROM ir_attachment WHERE store_fname IS NOT NULL AND (res_model IN ('res.partner','hr.employee','discuss.channel') OR id IN (SELECT attachment_id FROM message_attachment_rel))" > "$LIST"
docker exec -i "$MC2_ODOO" tar -C /var/lib/odoo/filestore/mc2 -cf - --ignore-failed-read -T - < "$LIST" \
  | docker exec -i dev-docker-odoo tar -C "/var/lib/odoo/filestore/$DB" -xf -
echo "fichiers copiés : $(wc -l < "$LIST")"
rm -f "$LIST"
