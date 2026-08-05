# Taste wall technical contract

## Deploy gates (live)

Netlify and Vercel both run:

```bash
python3 scripts/validate_taste_wall.py
```

as the build command. A failing gate fails the deploy.

## GitHub Actions

Workflow file: `.github/workflows/taste-wall-contract.yml`  
Runs on every push to `main` and every PR when present on the default branch.

## Local

```bash
python3 scripts/validate_taste_wall.py
./scripts/taste_wall_gate.sh
```

Exit `0` = pass. Exit `1` = per-file violations.

## Rules

- Exactly one `<h1>`
- `<nav aria-label="Primary">` on every page
- `id="contact"` on `<footer>` (not a nested span)
- Every `href="#x"` resolves to `id="x"`
- Section ids on semantic hosts
- De-emphasis via `--muted` / `--mute` — **no `opacity` in `<style>` or inline `style=`**
- Single `:root`; valid CSS custom-property tokens

## Autofix

```bash
python3 scripts/fix_taste_wall_contract.py
python3 scripts/validate_taste_wall.py
```
