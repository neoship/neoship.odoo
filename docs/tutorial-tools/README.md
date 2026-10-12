# Tutorial database

`docs/tutorial.html` (and `tutorial-sk.html`) was captured on a local database with realistic
Slovak and Czech data: the coffee roastery Zrnko s.r.o. in Bratislava, its warehouse
Sklad Bratislava (`BA/OUT/…`), seven products with weights and 23 % VAT included in the price,
Slovak and Czech customers and a few earlier orders. All orders are in EUR; the order tag
`Dobierka` marks cash on delivery and `Platba kartou` a card payment.

## Recreate it

```bash
docker compose up -d
docker compose run --rm odoo odoo -d neoship_tutorial -i base --without-demo=True --stop-after-init
# 1st run: Slovak company with EUR, so that Accounting installs the Slovak chart of accounts
docker compose exec -T odoo odoo shell -d neoship_tutorial --no-http < docs/tutorial-tools/seed_data.py
docker compose run --rm odoo odoo -d neoship_tutorial -i sale_management,stock_delivery,delivery_neoship --stop-after-init
# 2nd run: warehouse, products, stock, customers, tags and order history
docker compose exec -T odoo odoo shell -d neoship_tutorial --no-http < docs/tutorial-tools/seed_data.py
```

Log in at <http://localhost:8069> as `admin` / `admin`. The script is idempotent and never
deletes anything.

The kit example in chapter 06 also needs `-i mrp,sale_mrp` (which installs `delivery_neoship_mrp`)
and the product Darčeková sada Ráno with a *Kit* bill of materials: 1 × Káva Etiópia 250 g and
1 × Hrnček Tatry. It is not seeded.

The Neoship delivery methods are not seeded: creating them, testing the connection and choosing
the carriers is chapter 02 of the tutorial. Use the test credentials from `.env`.

Validating a delivery creates a real shipment on the Neoship test API and uses test credit.
Cancel test shipments when you are done (chapter 09) and never run a closure on the shared
test account (chapter 10).

## Orders for manual testing

`test_orders.py` creates one confirmed order per tutorial scenario, with a ready delivery and the
expected result in the log. Their Customer Reference starts with `TEST` (filter the Sales list by it):

```bash
docker compose run --rm odoo odoo -d neoship_tutorial -i mrp,sale_mrp --stop-after-init  # kits, optional
docker compose exec -T odoo odoo shell -d neoship_tutorial --no-http < docs/tutorial-tools/test_orders.py
```

It needs the Neoship delivery methods from chapter 02 (Kuriér SPS, Kuriér GLS, Kuriér DPD,
Packeta – doručenie domov SK and CZ) and skips a scenario whose method is missing. A scenario gets a
new order only when the previous one has no delivery left to process, so run the script again after
testing. Cancel the test shipments afterwards (chapter 09).
