# Recovered material from `odoomaroc/zk_odoo`

Everything salvaged while fixing the `docs/addons` gitlink (see
`../addons-submodule-fix.md`). Kept for reference — the live code is
`docs/addons/nabi_hr`.

## Contents

| Path | What it is |
|---|---|
| `zk_odoo-full-history.bundle` | Complete zk_odoo repo — all commits, all branches |
| `archives/addons.tar.gz` | Snapshot deleted in zk_odoo history (64 entries) |
| `archives/nabi_hr.tar.gz` | Snapshot deleted in zk_odoo history (26 entries) |
| `archives/nabi_hr_2.tar.gz` | Snapshot deleted in zk_odoo history (28 entries) |
| `extracted/` | The three archives unpacked, for direct browsing |

## Restoring the full history

```bash
git clone docs/recovered/zk_odoo-full-history.bundle zk_odoo
```

## Status

All three archives are older snapshots of `nabi_hr` only — no other module has
ever existed in zk_odoo. They contain monolithic `models/models.py` and
`controllers/controllers.py`, since split into `Attendance.py`, `Leaves.py`,
`Personnel.py` and others. All 9 class/method definitions in the old
`models.py` are present in the current code (64 total), so nothing was lost in
the refactor. These files are superseded — reference only.
