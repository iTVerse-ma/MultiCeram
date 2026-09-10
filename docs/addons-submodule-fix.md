# Fixing `docs/addons` — submodule pointer → tracked files

**Date:** 2026-09-10
**Repo:** `iTVerse-ma/MultiCeram` (branch `master`)

## Problem

`docs/addons` appeared on GitHub as a grey, unopenable folder.

It had been committed as a **gitlink** (mode `160000`) pointing at commit
`15a2d01` of `odoomaroc/zk_odoo`, with **no `.gitmodules`** file. Git stored a
commit pointer, not the files, so none of the addon code was ever uploaded to
MultiCeram. The cause: `docs/addons/` contained its own `.git` directory when it
was staged.

Diagnose with:

```bash
git ls-files -s | awk '$1=="160000"'
```

## Fix applied

1. Backed up the inner repo: `docs/addons/.git` → `Desktop\zk_odoo_git_backup`
2. Removed the pointer: `git rm --cached docs/addons`
3. Added root `.gitignore` (`__pycache__/`, `*.py[cod]`, `.DS_Store`, `*.log`)
4. Staged and committed all 49 `nabi_hr` files as regular files
5. Restored `docs/addons/.gitignore` from zk_odoo HEAD (deleted in working copy)
6. Pushed `eb29ad8` and `51413b9` to `master`

## Restore audit — nothing lost

- `nabi_hr` is the **only** module that has ever existed in `zk_odoo`, across all
  branches and all commits
- Recovered 3 tarballs deleted in history: `addons.tar.gz`, `nabi_hr.tar.gz`,
  `nabi_hr_2.tar.gz` — all older snapshots of `nabi_hr` only
- They contain monolithic `models/models.py` and `controllers/controllers.py`,
  since split into `Attendance.py`, `Leaves.py`, `Personnel.py`, etc.
- All 9 class/method definitions from the old `models.py` exist in the current
  code (64 definitions total) — nothing dropped in the refactor
- Every file in `zk_odoo` HEAD is now tracked in MultiCeram

## Consequences

- **The link to `odoomaroc/zk_odoo` is severed.** Changes under `docs/addons`
  now go to MultiCeram only; that repo will not receive them.
- The zk_odoo history remains at `Desktop\zk_odoo_git_backup` and on GitHub.
- The recovered tarballs were written to session temp
  (`%TEMP%\claude_zk_restore`) and are not preserved — they are fully superseded.

## Avoiding a repeat

Before committing a directory, check it is not its own repo:

```bash
find . -mindepth 2 -name .git -maxdepth 3
```

If a nested `.git` exists, either remove it (to absorb the files) or register a
proper submodule with `git submodule add <url> <path>`.
