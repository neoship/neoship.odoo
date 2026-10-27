"""Realistic Slovak and Czech data for the Neoship tutorial database.

Run it in an Odoo shell (see docs/tutorial-tools/README.md):

    docker compose exec -T odoo odoo shell -d neoship_tutorial --no-http < docs/tutorial-tools/seed_data.py

Run it once on a database with only `base` installed, so that the company is Slovak and uses EUR
before Accounting picks its chart of accounts, then install the apps and run it again.
The script is idempotent: records are looked up by name before they are created.
"""

import logging
from datetime import timedelta

from odoo import SUPERUSER_ID, Command, api, fields

_logger = logging.getLogger('neoship.tutorial')

COMPANY = {
    'name': 'Zrnko s.r.o.',
    'street': 'Panónska cesta 7',
    'zip': '851 04',
    'city': 'Bratislava',
    'email': 'expedicia.zrnko@example.com',
    'phone': '+421 2 3456 7890',
    'website': 'https://zrnko.example.com',
    'company_registry': '53 123 456',
}
ADMIN_NAME = 'Mária Kollárová'
TIMEZONE = 'Europe/Bratislava'
WAREHOUSE = {'name': 'Sklad Bratislava', 'code': 'BA'}

PRODUCTS = [
    # name, internal reference, price incl. 23 % VAT, weight in kg
    ('Káva Etiópia Yirgacheffe, zrnková 250 g', 'ZR-ETI-250', 11.90, 0.28),
    ('Káva Kolumbia Huila, zrnková 1 kg', 'ZR-KOL-1000', 34.90, 1.05),
    ('Káva Brazília Santos, mletá 500 g', 'ZR-BRA-500', 15.90, 0.53),
    ('Hrnček Tatry, keramika 350 ml', 'HR-TAT-350', 12.90, 0.42),
    ('Ručný mlynček na kávu', 'ML-RUC-01', 49.90, 0.95),
    ('Darčeková sada Degustácia 3 × 250 g', 'DS-DEG-03', 32.90, 0.95),
    ('Papierové filtre V60, 100 ks', 'FI-V60-100', 6.90, 0.12),
]
STOCK_QUANTITY = 120

MAIL_DOMAIN = 'example.com'
CUSTOMERS = [
    # name, street, zip, city, country, mailbox at example.com, phone
    ('Jana Nováková', 'Hlavná 12', '040 01', 'Košice', 'sk', 'jana.novakova', '+421 905 123 456'),
    ('Martin Kováč', 'Štúrova 27', '949 01', 'Nitra', 'sk', 'martin.kovac', '+421 908 234 567'),
    ('Zuzana Horváthová', 'Mierová 45', '821 05', 'Bratislava', 'sk', 'zuzana.horvathova', '+421 915 345 678'),
    ('Peter Baláž', 'Námestie SNP 8', '974 01', 'Banská Bystrica', 'sk', 'peter.balaz', '+421 949 456 789'),
    ('Lucia Vargová', 'Hurbanova 15', '010 01', 'Žilina', 'sk', 'lucia.vargova', '+421 902 567 890'),
    ('Tomáš Šimko', 'Hlavná 61', '080 01', 'Prešov', 'sk', 'tomas.simko', '+421 918 678 901'),
    ('Petr Svoboda', 'Vinohradská 48', '120 00', 'Praha 2', 'cz', 'petr.svoboda', '+420 777 123 456'),
    ('Kateřina Dvořáková', 'Masarykova 21', '602 00', 'Brno', 'cz', 'katerina.dvorakova', '+420 603 234 567'),
    ('Jakub Procházka', 'Nádražní 15', '702 00', 'Ostrava', 'cz', 'jakub.prochazka', '+420 731 345 678'),
    ('Anna Kowalska', 'Pawia 5', '31-154', 'Kraków', 'pl', 'anna.kowalska', '+48 512 345 678'),
]
BUSINESS_CUSTOMER = {
    'name': 'Kaviareň Pod Hradom s.r.o.',
    'street': 'Hlavná 9',
    'zip': '917 01',
    'city': 'Trnava',
    'email': 'objednavky.podhradom@example.com',
    'phone': '+421 33 512 3456',
    'vat': 'SK2120123456',
    'contact': ('Andrea Molnárová', 'andrea.molnarova@example.com', '+421 907 789 012'),
}

# Sales order tags set by the e-shop; the Neoship cash on delivery rule matches COD_TAG.
COD_TAG = 'Dobierka'
CARD_TAG = 'Platba kartou'

# A box of our own, without a carrier integration: name, length, width, height in cm, empty weight in kg
WAREHOUSE_BOX = ('Krabica 30 × 20 × 15 cm', 30, 20, 15, 0.2)

PICKUP_METHOD = 'Osobný odber – Bratislava'
HISTORY = [
    # customer, days ago, lines (internal reference, quantity), payment tag, delivered
    ('Zuzana Horváthová', 21, [('ZR-ETI-250', 2), ('FI-V60-100', 1)], CARD_TAG, True),
    ('Kaviareň Pod Hradom s.r.o.', 18, [('ZR-KOL-1000', 6), ('ZR-BRA-500', 4)], COD_TAG, True),
    ('Martin Kováč', 12, [('ML-RUC-01', 1), ('ZR-ETI-250', 1)], COD_TAG, True),
    ('Zuzana Horváthová', 6, [('DS-DEG-03', 1)], CARD_TAG, True),
    ('Kaviareň Pod Hradom s.r.o.', 3, [('ZR-KOL-1000', 4), ('HR-TAT-350', 6)], COD_TAG, False),
]
QUOTATIONS = [
    ('Lucia Vargová', [('DS-DEG-03', 2), ('HR-TAT-350', 2)]),
    ('Kateřina Dvořáková', [('ZR-ETI-250', 3)]),
]


def get_or_create(env, model, domain, values):
    record = env[model].with_context(active_test=False).search(domain, limit=1)
    return record or env[model].create(values)


def setup_country(env):
    eur = env.ref('base.EUR')
    eur.active = True
    env.company.write({**COMPANY, 'country_id': env.ref('base.sk').id, 'currency_id': eur.id})


def setup_company(env):
    company = env.company
    company.write({**COMPANY, 'account_price_include': 'tax_included'})
    company.partner_id.tz = TIMEZONE
    env.ref('base.user_admin').write({'name': ADMIN_NAME, 'tz': TIMEZONE})
    warehouse = env['stock.warehouse'].search([('company_id', '=', company.id)], limit=1)
    if warehouse.code != WAREHOUSE['code']:
        warehouse.write(WAREHOUSE)
    env['res.config.settings'].create({'group_stock_tracking_lot': True}).execute()
    return warehouse


def setup_products(env, warehouse):
    tax = env.company.account_sale_tax_id
    products = {}
    for name, code, price, weight in PRODUCTS:
        products[code] = get_or_create(
            env,
            'product.product',
            [('default_code', '=', code)],
            {
                'name': name,
                'default_code': code,
                'type': 'consu',
                'is_storable': True,
                'list_price': price,
                'weight': weight,
                'taxes_id': [Command.set(tax.ids)],
            },
        )
    for product in products.values():
        if product.qty_available < STOCK_QUANTITY / 2:
            env['stock.quant'].with_context(inventory_mode=True).create(
                {
                    'product_id': product.id,
                    'location_id': warehouse.lot_stock_id.id,
                    'inventory_quantity': STOCK_QUANTITY,
                }
            ).action_apply_inventory()
    return products


def setup_customers(env):
    customers = {}
    for name, street, zip_code, city, country, mailbox, phone in CUSTOMERS:
        customers[name] = get_or_create(
            env,
            'res.partner',
            [('name', '=', name)],
            {
                'name': name,
                'street': street,
                'zip': zip_code,
                'city': city,
                'country_id': env.ref(f'base.{country}').id,
                'email': f'{mailbox}@{MAIL_DOMAIN}',
                'phone': phone,
            },
        )
    business = BUSINESS_CUSTOMER
    contact_name, contact_email, contact_phone = business['contact']
    company = get_or_create(
        env,
        'res.partner',
        [('name', '=', business['name'])],
        {
            **{key: value for key, value in business.items() if key != 'contact'},
            'is_company': True,
            'country_id': env.ref('base.sk').id,
            'child_ids': [
                Command.create(
                    {'name': contact_name, 'email': contact_email, 'phone': contact_phone, 'function': 'Prevádzkarka'}
                )
            ],
        },
    )
    customers[business['name']] = company
    return customers


def setup_package_types(env):
    name, length, width, height, weight = WAREHOUSE_BOX
    cm = env.ref('uom.product_uom_cm')
    length_uom = env['product.template']._get_length_uom_id_from_ir_config_parameter()
    get_or_create(
        env,
        'stock.package.type',
        [('name', '=', name)],
        {
            'name': name,
            'packaging_length': cm._compute_quantity(length, length_uom, round=False),
            'width': cm._compute_quantity(width, length_uom, round=False),
            'height': cm._compute_quantity(height, length_uom, round=False),
            'base_weight': weight,
        },
    )


def setup_tags(env):
    for name in (COD_TAG, CARD_TAG):
        get_or_create(env, 'crm.tag', [('name', '=', name)], {'name': name})


def setup_pickup_method(env):
    product = get_or_create(
        env,
        'product.product',
        [('name', '=', PICKUP_METHOD)],
        {'name': PICKUP_METHOD, 'type': 'service', 'sale_ok': False, 'list_price': 0.0},
    )
    return get_or_create(
        env,
        'delivery.carrier',
        [('name', '=', PICKUP_METHOD)],
        {'name': PICKUP_METHOD, 'delivery_type': 'fixed', 'fixed_price': 0.0, 'product_id': product.id},
    )


def create_order(env, customer, lines, carrier=None, date=None):
    order = env['sale.order'].create(
        {
            'partner_id': customer.id,
            'user_id': env.ref('base.user_admin').id,
            'order_line': [
                Command.create({'product_id': product.id, 'product_uom_qty': quantity}) for product, quantity in lines
            ],
        }
    )
    if carrier:
        order.set_delivery_line(carrier, carrier.fixed_price)
    if date:
        order.date_order = date
    return order


def setup_history(env, products, customers):
    if env['sale.order'].search_count([]):
        return
    pickup = setup_pickup_method(env)
    now = fields.Datetime.now()
    tags = {tag.name: tag for tag in env['crm.tag'].search([('name', 'in', [COD_TAG, CARD_TAG])])}
    for customer, days, lines, tag, delivered in HISTORY:
        order_lines = [(products[code], quantity) for code, quantity in lines]
        order = create_order(env, customers[customer], order_lines, pickup, now - timedelta(days=days))
        order.tag_ids = tags[tag]
        order.action_confirm()
        order.date_order = now - timedelta(days=days)
        if delivered:
            order.picking_ids.move_ids.picked = True
            order.picking_ids.with_context(skip_sms=True).button_validate()
    for customer, lines in QUOTATIONS:
        create_order(env, customers[customer], [(products[code], quantity) for code, quantity in lines])


def seed(env):
    if 'sale.order' not in env:
        setup_country(env)
        _logger.info('Company set to Slovakia and EUR. Install the apps, then run this script again.')
        return
    warehouse = setup_company(env)
    products = setup_products(env, warehouse)
    customers = setup_customers(env)
    setup_tags(env)
    setup_package_types(env)
    setup_history(env, products, customers)
    _logger.info(
        'Tutorial data ready: %s products, %s customers, %s sales orders',
        len(products),
        len(customers),
        env['sale.order'].search_count([]),
    )


with env.registry.cursor() as seed_cr:  # noqa: F821 - env is provided by odoo shell
    seed(api.Environment(seed_cr, SUPERUSER_ID, {}))
