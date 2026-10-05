{
    'name': 'Neoship Shipping',
    'summary': 'Send shipments through Neoship and track their delivery',
    'category': 'Shipping Connectors',
    'version': '19.0.0.1.0',
    'depends': ['stock_delivery'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/neoship_option_wizard_views.xml',
        'views/delivery_carrier_views.xml',
        'views/stock_picking_views.xml',
    ],
    'author': 'Neoship',
    'license': 'LGPL-3',
    'installable': True,
}
