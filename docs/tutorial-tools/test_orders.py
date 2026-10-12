"""Confirmed sales orders for testing the tutorial scenarios by hand.

Run it in an Odoo shell after seed_data.py and after creating the Neoship delivery methods (chapter 02):

    docker compose exec -T odoo odoo shell -d neoship_tutorial --no-http < docs/tutorial-tools/test_orders.py

Every scenario gets one order whose Customer Reference starts with "TEST". The script skips a scenario
while its order still has a delivery to process, so run it again to get fresh orders for finished ones.
With Manufacturing and Sales installed (mrp, sale_mrp) it also creates the kit Darčeková sada Ráno.
"""

import logging

from odoo import SUPERUSER_ID, Command, api

_logger = logging.getLogger('neoship.tutorial')

COD_TAG = 'Dobierka'
CARD_TAG = 'Platba kartou'
SPS = 'Kuriér SPS'
GLS = 'Kuriér GLS'
DPD = 'Kuriér DPD'
PACKETA_SK = 'Packeta – doručenie domov SK'
PACKETA_CZ = 'Packeta – doručenie domov CZ'
PICKUP_POINT = '19407'
MIN_STOCK = 60
STOCK_QUANTITY = 120

KIT = ('Darčeková sada Ráno', 'DS-RAN-02', 22.90, 0.70, [('ZR-ETI-250', 1), ('HR-TAT-350', 1)])

SCENARIOS = [
    # reference, customer, lines, delivery method, payment tag, extra values, what to do and expect
    (
        'TEST 03 SPS dobierka',
        'Jana Nováková',
        [('ZR-ETI-250', 2), ('HR-TAT-350', 1)],
        SPS,
        COD_TAG,
        {},
        'Validate the delivery: COD 40.60 € (whole order).',
    ),
    (
        'TEST 03 GLS dobierka',
        'Martin Kováč',
        [('ZR-KOL-1000', 1), ('HR-TAT-350', 1)],
        GLS,
        COD_TAG,
        {},
        'Validate: GLS label prints the COD amount 51.70 €.',
    ),
    (
        'TEST 03 DPD karta',
        'Peter Baláž',
        [('ZR-BRA-500', 2)],
        DPD,
        CARD_TAG,
        {},
        'Validate: prepaid, no COD.',
    ),
    (
        'TEST 04 Packeta CZ karta',
        'Petr Svoboda',
        [('ZR-ETI-250', 2), ('HR-TAT-350', 2)],
        PACKETA_CZ,
        CARD_TAG,
        {},
        'Validate: Czech home delivery without COD.',
    ),
    (
        'TEST 04 Packeta CZ dobierka',
        'Petr Svoboda',
        [('ZR-ETI-250', 1)],
        PACKETA_CZ,
        COD_TAG,
        {},
        'Validate: the test account refuses COD to CZ (HTTP 422); switch the tag to Platba kartou and validate again.',
    ),
    (
        'TEST 05 výdajné miesto',
        'Lucia Vargová',
        [('DS-DEG-03', 2), ('HR-TAT-350', 2)],
        PACKETA_SK,
        COD_TAG,
        {'neoship_parcelshop_id': PICKUP_POINT},
        'Validate: Z-BOX Žilina 19407, COD 94.50 €.',
    ),
    (
        'TEST 06 dve škatule SPS',
        'Zuzana Horváthová',
        [('ML-RUC-01', 1), ('DS-DEG-03', 1)],
        SPS,
        CARD_TAG,
        {},
        'Put each product in its own Destination Package, then validate: one SPS shipment with 2 parcels.',
    ),
    (
        'TEST 06 čiastočné dodávky',
        'Kaviareň Pod Hradom s.r.o.',
        [('ZR-KOL-1000', 6)],
        SPS,
        COD_TAG,
        {},
        'Deliver 3 bags with a backorder: 108.60 €; then the backorder: 104.70 €.',
    ),
    (
        'TEST 06 osobný odber + kuriér',
        'Zuzana Horváthová',
        [('ZR-KOL-1000', 4)],
        SPS,
        COD_TAG,
        {},
        'Set the carrier Osobný odber – Bratislava, deliver 2 bags with a backorder, '
        'set Kuriér SPS on the backorder and validate it: 69.80 €.',
    ),
    (
        'TEST 06 sada',
        'Jana Nováková',
        [('DS-RAN-02', 2)],
        SPS,
        COD_TAG,
        {},
        'Deliver 2 coffees and 1 mug with a backorder: 26.80 €; then the backorder: 22.90 €.',
    ),
    (
        'TEST 06 zľava',
        'Tomáš Šimko',
        [('HR-TAT-350', 3)],
        SPS,
        COD_TAG,
        {'discount': 20.0},
        'Deliver 1 mug with a backorder: no COD (−3.20 €); then the backorder: 22.60 €.',
    ),
    (
        'TEST 06 ručná suma',
        'Kaviareň Pod Hradom s.r.o.',
        [('ZR-KOL-1000', 2)],
        SPS,
        COD_TAG,
        {},
        'Customer prepaid 30 €: tick Manual Cash on Delivery, enter 43.70 and validate.',
    ),
    (
        'TEST 07 Packeta nad 15 kg',
        'Peter Baláž',
        [('ZR-KOL-1000', 15)],
        PACKETA_SK,
        CARD_TAG,
        {},
        'Validate: refused at 15.75 kg; split into two packages (8 + 7) and validate again.',
    ),
]


def setup_kit(env, products):
    name, code, price, weight, components = KIT
    product = env['product.product'].search([('default_code', '=', code)], limit=1)
    if not product:
        product = env['product.product'].create(
            {
                'name': name,
                'default_code': code,
                'type': 'consu',
                'is_storable': True,
                'list_price': price,
                'weight': weight,
                'taxes_id': [Command.set(env.company.account_sale_tax_id.ids)],
            }
        )
    if not env['mrp.bom'].search_count([('product_tmpl_id', '=', product.product_tmpl_id.id)]):
        env['mrp.bom'].create(
            {
                'product_tmpl_id': product.product_tmpl_id.id,
                'type': 'phantom',
                'bom_line_ids': [
                    Command.create({'product_id': products[component].id, 'product_qty': quantity})
                    for component, quantity in components
                ],
            }
        )
    products[code] = product


def top_up_stock(env, products):
    location = env['stock.warehouse'].search([('company_id', '=', env.company.id)], limit=1).lot_stock_id
    for product in products.values():
        if product.is_storable and not product.bom_ids and product.qty_available < MIN_STOCK:
            env['stock.quant'].with_context(inventory_mode=True).create(
                {'product_id': product.id, 'location_id': location.id, 'inventory_quantity': STOCK_QUANTITY}
            ).action_apply_inventory()


def is_open(order):
    return any(picking.state not in ('done', 'cancel') for picking in order.picking_ids)


def create_scenario(env, products, carriers, tags, scenario):
    reference, customer, lines, method, tag, extra, _note = scenario
    if any(is_open(order) for order in env['sale.order'].search([('client_order_ref', '=', reference)])):
        return None
    if method not in carriers or any(code not in products for code, _quantity in lines):
        _logger.warning('%s skipped: delivery method %s or a product is missing', reference, method)
        return None
    discount = extra.get('discount')
    order = env['sale.order'].create(
        {
            'partner_id': env['res.partner'].search([('name', '=', customer)], limit=1).id,
            'client_order_ref': reference,
            'tag_ids': [Command.set(tags[tag].ids)],
            'neoship_parcelshop_id': extra.get('neoship_parcelshop_id'),
            'order_line': [
                Command.create({'product_id': products[code].id, 'product_uom_qty': quantity})
                for code, quantity in lines
            ],
        }
    )
    carrier = carriers[method]
    order.set_delivery_line(carrier, carrier.fixed_price)
    if discount:
        env['sale.order.discount'].create(
            {'sale_order_id': order.id, 'discount_type': 'amount', 'discount_amount': discount}
        ).action_apply_discount()
    order.action_confirm()
    return order


def prepare(env):
    coded = env['product.product'].search([('default_code', '!=', False)])
    products = {product.default_code: product for product in coded}
    if 'mrp.bom' in env:
        setup_kit(env, products)
    else:
        _logger.warning('Manufacturing is not installed: install mrp and sale_mrp to test kits')
    top_up_stock(env, products)
    carriers = {carrier.name: carrier for carrier in env['delivery.carrier'].search([])}
    tags = {tag.name: tag for tag in env['crm.tag'].search([('name', 'in', [COD_TAG, CARD_TAG])])}
    for scenario in SCENARIOS:
        order = create_scenario(env, products, carriers, tags, scenario)
        if order:
            _logger.info(
                '%s: %s %s, %s, %.2f € → %s',
                scenario[0],
                order.name,
                order.picking_ids.name,
                scenario[1],
                order.amount_total,
                scenario[-1],
            )


with env.registry.cursor() as test_cr:  # noqa: F821 - env is provided by odoo shell
    prepare(api.Environment(test_cr, SUPERUSER_ID, {}))
