# -*- coding: utf-8 -*-
"""Copie intégrale des données de mc2 (Odoo 18) dans multiceram_nabi (Odoo 19), à l'identique.

Demande du 15/09/2026 : « une copie 1:1 en Odoo 19 ». Complète 30_load_nabi19.py (départements, employés,
terminaux, paramètres, pointages de septembre-octobre) avec tout le reste :
- contacts, utilisateurs (sans mot de passe), groupes, sociétés, lien employé ↔ utilisateur et approbateur de congés ;
- canaux de discussion et membres ;
- congés, jours fériés et congés du calendrier, rendez-vous ;
- jours de repos (x_jour_repos, identifiants d'origine) ;
- tous les pointages (identifiants d'origine, copies et marques de doublons comprises) ;
- images des contacts et employés, pièces jointes des messages ;
- historique (messages, suivis de valeurs, abonnés, notifications, courriels en erreur) ;
- divers : page /my/leaves, produit, correspondances d'import, paramètres, visites du site, journaux de connexion.
Non repris volontairement : mots de passe, jetons et mots de passe des API (BioTime, CVSecurity, IAP).

Source : schéma `mc2` (copie complète de la base mc2 restaurée dans multiceram_nabi). Copie en SQL avec
correspondance des identifiants : clés étrangères lues dans les contraintes, puis xmlid, code ou nom.
Correspondances enregistrées dans legacy.itv_map. Une seule exécution (verrou nabi19.full_copy).

    docker compose exec -T [-e DRY_RUN=1] odoo odoo shell -c /etc/odoo/odoo.conf -d multiceram_nabi \\
      --db_host db --db_user odoo --db_password <PG_PASSWORD> --http-port 8169 < tools/migration_nabi/40_full_copy_mc2.py
"""
import collections
import os
import time

from psycopg2.extras import Json

DRY_RUN = os.environ.get('DRY_RUN') == '1'
LOCK_KEY = 'nabi19.full_copy'
SECRET_WORDS = ('password', 'token', 'secret', 'uuid')
IGNORED_PARAMS = {'web.base.url', 'base.template_portal_user_id', 'database.create_date', 'database.enterprise_code'}
# Modèles dont les messages créés par le chargement Odoo 19 sont remplacés par l'historique de mc2.
CHATTER_REPLACED = ('hr.employee', 'hr.department', 'res.partner', 'discuss.channel', 'crm.team',
                    'crm.team.member', 'product.category', 'mailing.contact', 'mailing.list')


def log(message, *args):
    print("copie mc2: " + (message % args if args else message), flush=True)


class Skip(Exception):
    """Ligne source sans équivalent possible : elle n'est pas copiée."""


class FullCopy:

    def __init__(self, environment):
        self.env = environment(context=dict(environment.context, active_test=False, tracking_disable=True,
                                            mail_create_nolog=True, mail_notrack=True, mail_create_nosubscribe=True))
        self.cr = self.env.cr
        self.warnings = collections.Counter()
        self.skipped = collections.Counter()
        self.inserted = collections.defaultdict(set)
        self._columns, self._fks, self._loaded = {}, {}, set()
        self.table_model = {}
        for name in self.env.registry:
            model = self.env[name]
            if not model._abstract and model._auto and model._table:
                self.table_model.setdefault(model._table, name)
        self.model_table = {model: table for table, model in self.table_model.items()}
        self.maps = collections.defaultdict(dict)
        self.cr.execute("SELECT model, legacy_id, new_id FROM legacy.itv_map")
        for model, old, new in self.cr.fetchall():
            self.maps[self.model_table.get(model, model)][old] = new
        self.preload_maps()

    # ------------------------------------------------------------------ outils

    def columns(self, schema, table):
        key = (schema, table)
        if key not in self._columns:
            self.cr.execute("""SELECT column_name, is_nullable = 'NO', column_default FROM information_schema.columns
                               WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position""", [schema, table])
            self._columns[key] = {name: {'notnull': notnull, 'default': default} for name, notnull, default in self.cr.fetchall()}
        return self._columns[key]

    def fks(self, table):
        if table not in self._fks:
            found = {}
            for schema in ('public', 'mc2'):
                self.cr.execute("""
                    SELECT a.attname, cl.relname FROM pg_constraint c
                      JOIN pg_class t ON t.oid = c.conrelid JOIN pg_namespace n ON n.oid = t.relnamespace
                      JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
                      JOIN pg_class cl ON cl.oid = c.confrelid
                     WHERE c.contype = 'f' AND array_length(c.conkey, 1) = 1 AND n.nspname = %s AND t.relname = %s""", [schema, table])
                for column, referenced in self.cr.fetchall():
                    found.setdefault(column, referenced)
            for column in ('create_uid', 'write_uid'):
                found.setdefault(column, 'res_users')
            self._fks[table] = found
        return self._fks[table]

    def set_map(self, table, old, new):
        self.maps[table][old] = new
        self.cr.execute("""INSERT INTO legacy.itv_map (model, legacy_id, new_id) VALUES (%s, %s, %s)
                           ON CONFLICT (model, legacy_id) DO UPDATE SET new_id = EXCLUDED.new_id""",
                        [self.table_model.get(table, table), old, new])

    def pairs(self, query, params=None):
        self.cr.execute(query, params)
        return self.cr.fetchall()

    def preload_maps(self):
        """Tables de référence sans xmlid fiable : correspondance par clé naturelle."""
        natural = {
            'ir_model': "SELECT s.id, p.id FROM mc2.ir_model s JOIN public.ir_model p ON p.model = s.model",
            'ir_model_fields': """SELECT s.id, p.id FROM mc2.ir_model_fields s
                                  JOIN public.ir_model_fields p ON p.model = s.model AND p.name = s.name""",
            'res_lang': "SELECT s.id, p.id FROM mc2.res_lang s JOIN public.res_lang p ON p.code = s.code",
            'res_country': "SELECT s.id, p.id FROM mc2.res_country s JOIN public.res_country p ON p.code = s.code",
            'res_currency': "SELECT s.id, p.id FROM mc2.res_currency s JOIN public.res_currency p ON p.name = s.name",
            'res_company': "SELECT s.id, p.id FROM mc2.res_company s JOIN public.res_company p ON p.id = s.id",
            'website': "SELECT s.id, p.id FROM mc2.website s JOIN public.website p ON p.id = s.id",
        }
        for table, query in natural.items():
            for old, new in self.pairs(query):
                self.maps[table].setdefault(old, new)

    def load_xmlids(self, table):
        if table in self._loaded:
            return
        self._loaded.add(table)
        model = self.table_model.get(table)
        if model:
            for old, new in self.pairs("""SELECT s.res_id, p.res_id FROM mc2.ir_model_data s
                                          JOIN public.ir_model_data p ON p.module = s.module AND p.name = s.name AND p.model = s.model
                                          WHERE s.model = %s""", [model]):
                self.maps[table].setdefault(old, new)

    def remap(self, table, value, label):
        self.load_xmlids(table)
        new = self.maps[table].get(value)
        if new is None:
            self.warnings["%s → %s introuvable" % (label, table)] += 1
        return new

    def record_ref(self, model_column, id_column, on_missing='skip'):
        """Many2oneReference (modèle + identifiant) : correspondance selon le modèle de la ligne."""
        def convert(row):
            model, res_id = row[model_column], row[id_column]
            if not model or not res_id:
                return res_id
            table = self.model_table.get(model)
            new = self.remap(table, res_id, "%s(%s)" % (id_column, model)) if table else None
            if new is None and on_missing == 'skip':
                raise Skip("%s absent" % model)
            return new
        return convert

    def convert_row(self, table, row, names, special, defer):
        fks = self.fks(table)
        target = self.columns('public', table)
        values = []
        for column in names:
            value = row[column]
            if column in special:
                value = special[column](row)
            elif column in defer:
                value = None
            elif value is not None and column in fks:
                value = self.remap(fks[column], value, "%s.%s" % (table, column))
            if isinstance(value, (dict, list)):
                value = Json(value)
            if value is None and target[column]['notnull'] and target[column]['default'] is None:
                raise Skip("%s.%s obligatoire sans correspondance" % (table, column))
            values.append(value)
        return values

    def copy(self, table, where='TRUE', params=None, special=None, drop=(), fixed=None, defer=(), keep_id=False, conflict=False):
        """Copie les lignes de mc2.<table> absentes de la correspondance, en convertissant les références."""
        special, fixed = special or {}, fixed or {}
        source, target = self.columns('mc2', table), self.columns('public', table)
        has_id = 'id' in source
        names = [c for c in source if c in target and c not in drop and c not in fixed and (keep_id or c != 'id')]
        required = [c for c, info in target.items()
                    if info['notnull'] and info['default'] is None and c not in names and c not in fixed and c != 'id']
        if required:
            raise ValueError("%s : colonnes obligatoires absentes de mc2 : %s" % (table, required))
        self.cr.execute("SELECT * FROM mc2.%s WHERE %s%s" % (table, where, " ORDER BY id" if has_id else ""), params)
        rows = self.cr.dictfetchall()
        columns = names + list(fixed)
        sql = "INSERT INTO public.%s (%s) VALUES (%s)%s%s" % (
            table, ", ".join('"%s"' % c for c in columns), ", ".join(["%s"] * len(columns)),
            " ON CONFLICT DO NOTHING" if conflict else "", " RETURNING id" if has_id else "")
        inserted = 0
        for row in rows:
            if has_id and row['id'] in self.maps[table]:
                continue
            try:
                values = self.convert_row(table, row, names, special, defer)
            except Skip as reason:
                self.skipped["%s : %s" % (table, reason)] += 1
                continue
            values += [value(row) if callable(value) else value for value in fixed.values()]
            self.cr.execute(sql, values)
            if has_id:
                result = self.cr.fetchone()
                if result:
                    self.set_map(table, row['id'], result[0])
                    self.inserted[table].add(row['id'])
                    inserted += 1
            else:
                inserted += self.cr.rowcount
        if keep_id and has_id and inserted:
            self.cr.execute("SELECT setval(pg_get_serial_sequence('public.%s', 'id'), (SELECT max(id) FROM public.%s))" % (table, table))
        log("%s : %s ligne(s) copiée(s) sur %s", table, inserted, len(rows))
        return inserted

    def update_from_source(self, table, olds, columns, special=None):
        """Recopie des colonnes de mc2 sur des lignes déjà présentes (références converties)."""
        special = special or {}
        target = self.columns('public', table)
        columns = [c for c in columns if c in target]
        if not olds or not columns:
            return 0
        fks = self.fks(table)
        self.cr.execute("SELECT id, %s FROM mc2.%s WHERE id = ANY(%%s)" % (", ".join('"%s"' % c for c in columns), table), [list(olds)])
        count = 0
        for row in self.cr.dictfetchall():
            new_id = self.maps[table].get(row['id'])
            if not new_id:
                continue
            sets = {}
            for column in columns:
                value = row[column]
                if column in special:
                    value = special[column](row)
                elif value is not None and column in fks:
                    value = self.remap(fks[column], value, "%s.%s" % (table, column))
                    if value is None:
                        continue
                if isinstance(value, (dict, list)):
                    value = Json(value)
                sets[column] = value
            if sets:
                self.cr.execute("UPDATE public.%s SET %s WHERE id = %%s" % (table, ", ".join('"%s" = %%s' % c for c in sets)),
                                list(sets.values()) + [new_id])
                count += 1
        return count

    def common_columns(self, table, exclude=()):
        source, target = self.columns('mc2', table), self.columns('public', table)
        return [c for c in source if c in target and c != 'id' and c not in exclude]

    # ------------------------------------------------------------------ étapes

    def users_partners(self):
        # Comptes système par xmlid, puis leurs contacts ; contacts de travail des employés ; ressources.
        self.load_xmlids('res_users')
        self.load_xmlids('res_partner')
        source_partner = dict(self.pairs("SELECT id, partner_id FROM mc2.res_users"))
        target_partner = dict(self.pairs("SELECT id, partner_id FROM public.res_users"))
        for old, new in list(self.maps['res_users'].items()):
            self.set_map('res_partner', source_partner[old], target_partner[new])
        target_employee = {row[0]: row[1:] for row in self.pairs("SELECT id, work_contact_id, resource_id FROM public.hr_employee")}
        for old_employee, old_contact, old_resource in self.pairs("SELECT id, work_contact_id, resource_id FROM mc2.hr_employee"):
            new_employee = self.maps['hr_employee'].get(old_employee)
            if new_employee in target_employee:
                # Contact déjà relié à un compte système (employé lié à « admin ») : le contact de travail Odoo 19 fait doublon.
                if old_contact and target_employee[new_employee][0] and old_contact not in self.maps['res_partner']:
                    self.set_map('res_partner', old_contact, target_employee[new_employee][0])
                self.set_map('resource_resource', old_resource, target_employee[new_employee][1])
        existing_partners = set(self.maps['res_partner'])

        self.copy('res_partner', defer=('parent_id', 'commercial_partner_id', 'user_id'))
        self.update_from_source('res_partner', existing_partners - self.inserted['res_partner'],
                                self.common_columns('res_partner', exclude=('parent_id', 'commercial_partner_id', 'user_id')))
        existing_users = set(self.maps['res_users'])
        self.copy('res_users', drop=('password',))
        self.update_from_source('res_users', existing_users,
                                self.common_columns('res_users', exclude=('password', 'login', 'partner_id', 'active', 'share')))
        self.update_from_source('res_partner', set(self.maps['res_partner']), ['parent_id', 'commercial_partner_id', 'user_id', 'create_uid', 'write_uid'],
                                special={'commercial_partner_id': lambda row: self.maps['res_partner'].get(row['commercial_partner_id'])})
        self.update_from_source('res_users', self.inserted['res_users'], ['create_uid', 'write_uid'])
        self.copy('res_groups_users_rel', conflict=True)
        self.copy('res_company_users_rel', conflict=True)
        # Employé « Administrator » créé par Odoo 19 à l'installation, absent de mc2 : supprimé (archivé à défaut).
        # Idem pour le département « Administration ».
        for model, table in (('hr.employee', 'hr_employee'), ('hr.department', 'hr_department')):
            for record in self.env[model].search([('id', 'not in', list(self.maps[table].values()))]):
                contact = record.work_contact_id if model == 'hr.employee' else None
                if contact and (contact.user_ids or contact.id in self.maps['res_partner'].values()):
                    contact = None  # contact d'un utilisateur (Administrator) : conservé
                try:
                    with self.cr.savepoint():
                        record.unlink()
                        if contact:
                            contact.unlink()
                        for orphan_model in ('hr.employee', 'hr.version', 'hr.department', 'res.partner'):
                            self.cr.execute("DELETE FROM public.mail_message m WHERE m.model = %%s AND NOT EXISTS (SELECT 1 FROM public.%s r WHERE r.id = m.res_id)"
                                            % self.model_table[orphan_model], [orphan_model])
                    log("%s propre à Odoo 19 supprimé : %s%s", model, record.id, " (et son contact %s)" % contact.id if contact else "")
                except Exception as exc:  # consigné, puis archivage
                    record.write({'active': False, **({'user_id': False} if model == 'hr.employee' else {})})
                    log("%s propre à Odoo 19 archivé : %s (%s)", model, record.id, exc)
        self.env.flush_all()
        done = self.update_from_source('hr_employee', set(self.maps['hr_employee']), ['user_id', 'leave_manager_id', 'work_contact_id'])
        log("employés reliés à leur utilisateur, contact et approbateur de congés : %s", done)
        mapped_partners = list(self.maps['res_partner'].values())
        for partner in self.env['res.partner'].search([('id', 'not in', mapped_partners)]):
            label = "%s %s" % (partner.id, partner.name)
            try:
                with self.cr.savepoint():
                    partner.unlink()
                log("contact en double supprimé : %s", label)
            except Exception as exc:  # consigné, puis archivage
                partner.write({'active': False})
                log("contact en double archivé : %s (%s)", partner.id, exc)

    def channels(self):
        self.load_xmlids('discuss_channel')
        # Conversations sans xmlid : même type et mêmes participants dans le nom (« OdooBot, Administrator » = « Administrator, OdooBot »).
        def key(name, kind):
            return kind, frozenset(part.strip() for part in (name or '').split(','))
        unmatched = {key(name, kind): new for new, name, kind in self.pairs("SELECT id, name, channel_type FROM public.discuss_channel")
                     if new not in self.maps['discuss_channel'].values()}
        for old, name, kind in self.pairs("SELECT id, name, channel_type FROM mc2.discuss_channel"):
            if old not in self.maps['discuss_channel'] and key(name, kind) in unmatched:
                self.set_map('discuss_channel', old, unmatched.pop(key(name, kind)))
        self.copy('discuss_channel', defer=('from_message_id', 'parent_channel_id'))
        self.copy('discuss_channel_res_groups_rel', conflict=True)

    def leaves(self):
        # Le congé de la reprise septembre-octobre est remplacé par la copie SQL de mc2 (valeurs d'origine).
        loaded = list(self.maps['hr_leave'].values())
        if loaded:
            self.cr.execute("DELETE FROM public.calendar_event WHERE res_model = 'hr.leave' AND res_id = ANY(%s)", [loaded])
            self.cr.execute("DELETE FROM public.resource_calendar_leaves WHERE holiday_id = ANY(%s)", [loaded])
            self.cr.execute("DELETE FROM public.mail_message WHERE model = 'hr.leave' AND res_id = ANY(%s)", [loaded])
            self.cr.execute("DELETE FROM public.mail_followers WHERE res_model = 'hr.leave' AND res_id = ANY(%s)", [loaded])
            self.cr.execute("DELETE FROM public.hr_leave WHERE id = ANY(%s)", [loaded])
            self.cr.execute("DELETE FROM legacy.itv_map WHERE model = 'hr.leave'")
            self.maps['hr_leave'].clear()
        self.copy('hr_leave', defer=('meeting_id',))
        self.copy('resource_calendar_leaves')
        self.copy('calendar_event', special={'res_id': self.record_ref('res_model', 'res_id', on_missing='null'),
                                             'res_model_id': lambda row: self.maps['ir_model'].get(row['res_model_id'])})
        self.copy('calendar_attendee')
        self.copy('calendar_event_res_partner_rel', conflict=True)
        self.update_from_source('hr_leave', self.inserted['hr_leave'], ['meeting_id'])
        # mc2 n'avait que ses 6 types : les types livrés par Odoo 19 (généraux et marocains) sont archivés.
        self.cr.execute("""UPDATE public.hr_leave_type SET active = false
                            WHERE active AND id <> ALL(%s) RETURNING id""", [list(self.maps['hr_leave_type'].values())])
        log("types de congé Odoo 19 archivés : %s", self.cr.rowcount)

    def rest_days(self):
        self.copy('x_jour_repos', keep_id=True)

    def punches(self):
        started = time.monotonic()
        source, target = self.columns('mc2', 'zk_transaction'), self.columns('public', 'zk_transaction')
        names = [c for c in source if c in target]
        fks = self.fks('zk_transaction')
        self.cr.execute("CREATE TEMP TABLE copy_map (tbl varchar, old integer, new integer, PRIMARY KEY (tbl, old)) ON COMMIT DROP")
        referenced = {fks[c] for c in names if c in fks}
        for table in referenced:
            self.load_xmlids(table)
            for old, new in self.maps[table].items():
                self.cr.execute("INSERT INTO copy_map VALUES (%s, %s, %s)", [table, old, new])
        select, joins = [], []
        for index, column in enumerate(names):
            if column in fks:
                joins.append("LEFT JOIN copy_map m%d ON m%d.tbl = '%s' AND m%d.old = x.\"%s\"" % (index, index, fks[column], index, column))
                select.append("m%d.new" % index)
            else:
                select.append('x."%s"' % column)
        self.cr.execute("DELETE FROM public.zk_transaction")
        self.cr.execute("INSERT INTO public.zk_transaction (%s) SELECT %s FROM mc2.zk_transaction x %s ORDER BY x.id" % (
            ", ".join('"%s"' % c for c in names), ", ".join(select), " ".join(joins)))
        count = self.cr.rowcount
        self.cr.execute("SELECT setval(pg_get_serial_sequence('public.zk_transaction', 'id'), (SELECT max(id) FROM public.zk_transaction))")
        log("zk_transaction : %s pointages copiés (identifiants d'origine) en %.1f s", count, time.monotonic() - started)

    def attachments(self):
        # Images des contacts et employés : celles d'Odoo 19 (avatars générés) sont remplacées par celles de mc2.
        for model, table in (('res.partner', 'res_partner'), ('hr.employee', 'hr_employee')):
            self.cr.execute("DELETE FROM public.ir_attachment WHERE res_model = %s AND res_field IS NOT NULL AND res_id = ANY(%s)",
                            [model, list(self.maps[table].values())])
        self.copy('ir_attachment',
                  where="(res_model IN ('res.partner', 'hr.employee') AND res_field IS NOT NULL) OR res_model = 'discuss.channel'"
                        " OR id IN (SELECT attachment_id FROM mc2.message_attachment_rel)",
                  special={'res_id': self.record_ref('res_model', 'res_id')}, defer=('original_id',))

    def misc_before_chatter(self):
        # Produit de test « qsdsqd » et correspondances naturelles des enregistrements créés à l'installation.
        def plain(value):
            # Nom traduit (jsonb) ou simple texte selon la version et le champ.
            if isinstance(value, dict):
                return value.get('en_US') or next(iter(value.values()), '')
            return value
        for old_template, name, kind in self.pairs("SELECT id, name, type FROM mc2.product_template"):
            if old_template not in self.maps['product_template']:
                template = self.env['product.template'].create({'name': plain(name), 'type': kind})
                self.set_map('product_template', old_template, template.id)
                for old_variant, in self.pairs("SELECT id FROM mc2.product_product WHERE product_tmpl_id = %s", [old_template]):
                    self.set_map('product_product', old_variant, template.product_variant_id.id)
        target = dict(self.pairs("SELECT complete_name, id FROM public.product_category"))
        for old, name in self.pairs("SELECT id, complete_name FROM mc2.product_category"):
            if name in target:
                self.set_map('product_category', old, target[name])
        for table in ('mailing_contact', 'mailing_list'):
            target = {plain(name): new for new, name in self.pairs("SELECT id, name FROM public.%s" % table)}
            for old, name in self.pairs("SELECT id, name FROM mc2.%s" % table):
                if plain(name) in target:
                    self.set_map(table, old, target[plain(name)])
        self.load_xmlids('crm_team')
        target = {(team, user): member for member, team, user in self.pairs("SELECT id, crm_team_id, user_id FROM public.crm_team_member")}
        for old, team, user in self.pairs("SELECT id, crm_team_id, user_id FROM mc2.crm_team_member"):
            key = (self.maps['crm_team'].get(team), self.maps['res_users'].get(user))
            if key in target:
                self.set_map('crm_team_member', old, target[key])

    def chatter(self):
        for model in CHATTER_REPLACED:
            table = self.model_table.get(model)
            if table and self.maps[table]:
                self.cr.execute("DELETE FROM public.mail_message WHERE model = %s AND res_id = ANY(%s)", [model, list(self.maps[table].values())])
        self.copy('mail_message', special={'res_id': self.record_ref('model', 'res_id')}, defer=('parent_id',))
        self.update_from_source('mail_message', self.inserted['mail_message'], ['parent_id'])
        self.copy('mail_tracking_value')
        self.copy('mail_message_res_partner_rel', conflict=True)
        self.copy('message_attachment_rel', conflict=True)
        self.copy('mail_mail')
        self.copy('mail_mail_res_partner_rel', conflict=True)
        self.copy('mail_notification')
        self.copy('mail_followers', special={'res_id': self.record_ref('res_model', 'res_id')}, conflict=True)
        self.copy('mail_followers_mail_message_subtype_rel', conflict=True)
        self.copy('discuss_channel_member', conflict=True, special={
            'new_message_separator': lambda row: self.maps['mail_message'].get(row['new_message_separator'], row['new_message_separator'])})
        # Membres ajoutés par Odoo 19 à l'installation et absents de mc2.
        wanted = {(self.maps['discuss_channel'].get(channel), self.maps['res_partner'].get(partner))
                  for channel, partner in self.pairs("SELECT channel_id, partner_id FROM mc2.discuss_channel_member WHERE partner_id IS NOT NULL")}
        extra = [member for member, channel, partner in self.pairs("SELECT id, channel_id, partner_id FROM public.discuss_channel_member")
                 if (channel, partner) not in wanted]
        if extra:
            self.cr.execute("DELETE FROM public.discuss_channel_member WHERE id = ANY(%s)", [extra])
        log("membres propres à Odoo 19 retirés : %s", len(extra))
        self.update_from_source('discuss_channel', set(self.maps['discuss_channel']), ['from_message_id', 'parent_channel_id'])

    def misc(self):
        self.copy('ir_ui_view', where="id IN (SELECT view_id FROM mc2.website_page WHERE url = '/my/leaves')",
                  defer=('inherit_id', 'model_data_id', 'theme_template_id'))
        self.copy('website_page', where="url = '/my/leaves'")
        self.copy('base_import_mapping')
        # Visites et connexions enregistrées sur le serveur de dev pendant les tests : remplacées par celles de mc2.
        for table in ('website_track', 'website_visitor', 'res_users_log', 'res_device_log'):
            self.cr.execute("DELETE FROM public.%s" % table)
            log("%s : %s ligne(s) de test supprimée(s)", table, self.cr.rowcount)
        pages =dict(self.pairs("SELECT DISTINCT ON (url) url, id FROM public.website_page ORDER BY url, id"))
        source_pages = dict(self.pairs("SELECT id, url FROM mc2.website_page"))
        # Jeton d'un visiteur connecté = identifiant de son contact : converti, puis fusion avec le visiteur Odoo 19 de même jeton.
        def visitor_token(row):
            token = row['access_token']
            if row['partner_id'] and token == str(row['partner_id']):
                token = str(self.maps['res_partner'].get(row['partner_id'], token))
            return token
        target_tokens = dict(self.pairs("SELECT access_token, id FROM public.website_visitor"))
        self.cr.execute("SELECT * FROM mc2.website_visitor")
        for row in self.cr.dictfetchall():
            if visitor_token(row) in target_tokens:
                self.set_map('website_visitor', row['id'], target_tokens[visitor_token(row)])
        self.copy('website_visitor', special={'access_token': visitor_token})
        self.copy('website_track', special={'page_id': lambda row: pages.get(source_pages.get(row['page_id']))})
        self.copy('res_users_log')
        self.copy('res_device_log')
        self.copy('digest_tip_res_users_rel', conflict=True)
        params = self.env['ir.config_parameter'].sudo()
        added = []
        for key, value in self.pairs("SELECT key, value FROM mc2.ir_config_parameter"):
            if key in IGNORED_PARAMS or any(word in key for word in SECRET_WORDS) or params.get_param(key) is not None:
                continue
            params.set_param(key, value)
            added.append(key)
        log("paramètres ajoutés : %s", ", ".join(added) or "aucun")

    def verify(self):
        tables = ('res_partner', 'res_users', 'res_groups_users_rel', 'res_company_users_rel', 'hr_employee', 'hr_department',
                  'zk_terminals', 'zk_transaction', 'x_jour_repos', 'hr_leave', 'resource_calendar_leaves', 'calendar_event',
                  'calendar_attendee', 'calendar_event_res_partner_rel', 'discuss_channel', 'discuss_channel_member',
                  'mail_message', 'mail_tracking_value', 'mail_followers', 'mail_followers_mail_message_subtype_rel',
                  'mail_notification', 'mail_mail', 'mail_message_res_partner_rel', 'message_attachment_rel',
                  'website_page', 'website_visitor', 'website_track', 'base_import_mapping', 'product_template',
                  'res_users_log', 'res_device_log', 'digest_tip_res_users_rel')
        log("%-42s %9s %9s", "table", "mc2", "odoo19")
        for table in tables:
            counts = [self.pairs("SELECT count(*) FROM %s.%s" % (schema, table))[0][0] for schema in ('mc2', 'public')]
            log("%-42s %9s %9s%s", table, counts[0], counts[1], "" if counts[0] == counts[1] else "  ≠")
        self.cr.execute("""SELECT count(*) FROM mc2.zk_transaction s FULL JOIN public.zk_transaction p ON p.id = s.id
                            WHERE p.id IS NULL OR s.id IS NULL OR p.punch_time IS DISTINCT FROM s.punch_time
                               OR p.emp_code IS DISTINCT FROM s.emp_code OR p.duplicate IS DISTINCT FROM s.duplicate
                               OR p.to_delete IS DISTINCT FROM s.to_delete OR p.upload_time IS DISTINCT FROM s.upload_time""")
        log("pointages différents de mc2 (id, heure, matricule, doublon, suppression, envoi) : %s", self.cr.fetchone()[0])

    def run(self):
        params = self.env['ir.config_parameter'].sudo()
        if params.get_param(LOCK_KEY):
            log("déjà exécutée le %s : arrêt", params.get_param(LOCK_KEY))
            return
        for step in ('users_partners', 'channels', 'leaves', 'rest_days', 'punches', 'attachments',
                     'misc_before_chatter', 'chatter', 'misc'):
            started = time.monotonic()
            log("— étape %s", step)
            getattr(self, step)()
            log("étape %s terminée en %.1f s", step, time.monotonic() - started)
        self.verify()
        for label, counter in (("lignes non copiées", self.skipped), ("références sans correspondance (mises à vide)", self.warnings)):
            if counter:
                log("%s :", label)
                for key, count in sorted(counter.items()):
                    log("  %6s  %s", count, key)
        if DRY_RUN:
            self.cr.rollback()
            log("ESSAI : tout est annulé")
        else:
            params.set_param(LOCK_KEY, time.strftime('%Y-%m-%d %H:%M:%S'))
            self.cr.commit()
            log("copie validée")


FullCopy(env).run()  # noqa: F821 — `env` est fourni par `odoo shell`
