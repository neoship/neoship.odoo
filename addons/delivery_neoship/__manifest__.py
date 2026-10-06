{
    'name': 'Neoship Shipping',
    'summary': 'Send shipments through Neoship and track their delivery',
    'category': 'Shipping Connectors',
    'version': '19.0.0.1.0',
    'depends': ['stock_delivery'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'wizard/neoship_option_wizard_views.xml',
        'views/delivery_carrier_views.xml',
        'views/stock_picking_views.xml',
        'views/sale_order_views.xml',
        'views/neoship_closure_views.xml',
    ],
    'author': 'Neoship',
    'license': 'LGPL-3',
    'installable': True,
}
