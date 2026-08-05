# Taste wall technical contract

**Runnable gate (this repo):**

```bash
python3 scripts/validate_taste_wall.py
# or
./scripts/taste_wall_gate.sh
```

Exit code `0` = all variants pass. Exit `1` = contract violations printed per file.

## Rules enforced

- Exactly one `<h1>`
- `<nav aria-label="Primary">` on every page
- `id="contact"` on `<footer>` (not a nested span)
- Every `href="#x"` resolves to `id="x"`
- Section ids on semantic hosts
- De-emphasis via `--muted` / `--mute` — **no `opacity` in `<style>` or inline `style=`**
- Single `:root`; valid CSS custom-property tokens

## Autofix (optional)

```bash
python3 scripts/fix_taste_wall_contract.py
python3 scripts/validate_taste_wall.py
```

Batch generators in the private Ziton tree call fix+validate before considering a run shipped.
