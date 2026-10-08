# Repository rules — Neoship × Odoo 19

## Translations

- Write every user-facing text in English; it is the translation source.
- Python models: wrap user-facing strings in `self.env._()` (Odoo 18+ style, enforced by pylint-odoo) and pass values as arguments — `self.env._('Shipment %s failed', ref)`. Never build translated text with f-strings, `%` or `+`.
- Views, field `string`/`help` and selection labels are extracted automatically; keep them as plain English. Omit `string=` when it equals the label Odoo derives from the field name.
- `models/neoship_api.py` has no Odoo environment. Its exceptions carry technical details only; turn them into translated `UserError` messages in the models.
- Do not create or update `i18n/*.pot` / `*.po` files yet. The Slovak translation is planned for a later phase.

## No magic values

- Do not repeat string literals for selection keys, states, carrier shortcuts, API action names or similar codes in Python. Define them once in `addons/delivery_neoship/const.py` and import them: `vals.get('delivery_type') == const.DELIVERY_TYPE`, not `== 'neoship'`.
- This includes Odoo core values our code depends on (e.g. `const.ODOO_DELIVERY_TYPE_FIXED`).
- Use plain module-level constants (or dicts/tuples of them for related sets). Odoo 19 supports Python 3.10, so `enum.StrEnum` is not available.
- Field names, Odoo framework keys (`'type': 'ir.actions.client'`, notification params) and HTTP methods/paths in the API client are not domain values and stay literal.
- XML views cannot import Python constants; literals there are fine, and tests must cover the behaviour they control.

## Lint and format

- Pre-commit runs Ruff (`pyproject.toml`: lint, format, Odoo import sections), pylint-odoo (`.pylintrc`: Odoo/manifest/translation checks) and OCA `odoo-pre-commit-hooks` (XML, CSV, PO checks).
- Before finishing a change run `ruff check --fix . && ruff format .`; the code must pass `pre-commit run --all-files`.
- Do not silence a rule with `noqa` without a reason in the same line.

## Tests

- Standard tests mock Neoship (`tests/common.py`, `mock_neoship`) and are tagged `post_install`, `-at_install`.
- Live tests against the Neoship test API use the `neoship_live` and `-standard` tags and read credentials from `.env`.
- `neoship_live_shipment` creates and cancels a real shipment on the test API (uses test credit); run it only when the create/label/cancel contract needs re-checking.

## Git

- No `Co-Authored-By` trailers or generated-with attribution in commits or PR/MR descriptions.
