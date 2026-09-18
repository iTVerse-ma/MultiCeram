# Site MultiCeram sur Odoo 19 (`multiceram_nabi`)

Le site de mc2 n'était pas du code : thème, variantes d'en-tête et de pied de page, contenus et réglages étaient
enregistrés dans la base. Ces scripts les rejouent sur une base Odoo 19 où `nabi_hr` et les modules du site sont installés.
Le JavaScript personnalisé de mc2 n'est pas ici : il fait partie du module (`nabi_hr/static/src/website_custom/`).

## Ordre (chaque script dans un `odoo shell` NEUF)

```bash
cd /srv/stacks/dev-docker; PG=$(grep '^PG_PASSWORD=' .env | cut -d= -f2)
run() { docker compose exec -T odoo odoo shell -c /etc/odoo/odoo.conf -d multiceram_nabi --db_host db --db_user odoo --db_password "$PG" --http-port 8169 < "$1"; }
W=repos/MultiCeram/tools/website_nabi19
run $W/61_apply_website.py      # thème theme_cobalt (valide lui-même la transaction), nom, variantes, accueil, CTA, popup, menus, liste Newsletter
run $W/62_finish_website.py     # variantes une à une + CTA + popup (à relancer dans un shell neuf après le thème)
run $W/63_fix_header_portal.py  # en-tête « boîte » (désactiver l'en-tête par défaut d'abord) + mise en page du portail (arch en_US)
run $W/64_set_identity.py       # société/site « Multicerame », homepage_url /my/home (le logo posé ici est remplacé par 66)
run $W/65_set_head_code.py      # code <head> de mc2 : Remix Icon + Bootstrap Icons (icônes des boutons nabi_hr)
run $W/66_set_real_logo.py      # vrai logo MULTICERAME (seule copie : res_company.logo_web de mc2) sur société et site
docker compose restart odoo     # valeurs écrites hors serveur : cache à vider
```

Chaque script affiche un rapport `OK` / `ECHEC` par étape ; une étape en échec n'arrête pas les suivantes.
Dans 61, l'étape « mise en page du portail » échoue (motif traduit) : c'est 63 qui la fait correctement.

## Pièges
- `button_choose_theme` valide lui-même la transaction : jamais dans un point de sauvegarde, et les étapes suivantes
  dans un shell neuf (sinon `KeyError ir.ui.view.is_seo_optimized`).
- Les modèles d'en-tête s'excluent : désactiver `website.template_header_default` avant d'activer `template_header_boxed`.
- Modifier les vues du portail avec `lang='en_US'`, sinon le texte traduit est enregistré comme source.

## `source_mc2/`
Données extraites de mc2 : arches des vues personnalisées (`custom_<id>.xml`) et de leurs modèles d'origine
(`base_<id>.xml`), état des variantes (`header_footer_states.txt`), feuilles SCSS (valeurs nulles, non reprises),
JavaScript personnalisé (asset 1566, repris dans le module), et les gabarits (`apply_template.py`, `finish_template.py`)
qui ont servi à générer 61 et 62 (`__STATES__` / `__ARCH_<id>__` remplacés par ces données).
