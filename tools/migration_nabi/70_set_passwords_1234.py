# -*- coding: utf-8 -*-
"""Mot de passe 1234 pour tous les comptes sauf admin (demande de Yahya, 15/09/2026, base de dev).

Les hachages de mc2 ne sont pas repris par 40_full_copy_mc2.py. Attention : le serveur de dev est sur un
port public et contient des données réelles. Un seul hachage, appliqué en SQL ; redémarrer le serveur ensuite.

    docker compose exec -T odoo odoo shell -c /etc/odoo/odoo.conf -d multiceram_nabi \\
      --db_host db --db_user odoo --db_password <PG_PASSWORD> --http-port 8169 < tools/migration_nabi/70_set_passwords_1234.py
"""
hashed = env['res.users']._crypt_context().hash('1234')  # noqa: F821 — `env` est fourni par `odoo shell`
env.cr.execute("UPDATE res_users SET password = %s WHERE login <> 'admin'", [hashed])  # noqa: F821
count = env.cr.rowcount  # noqa: F821
env.cr.commit()  # noqa: F821
print("mots de passe 1234 posés sur %s compte(s) (admin inchangé)" % count)
