from odoo import fields, models

from .. import const


class StockPackageType(models.Model):
    _inherit = 'stock.package.type'

    package_carrier_type = fields.Selection(
        selection_add=[(const.DELIVERY_TYPE, 'Neoship')], ondelete={const.DELIVERY_TYPE: 'set default'}
    )
    neoship_carrier_type = fields.Integer(
        string='Packeta Carrier ID',
        help='Packeta carrier whose size category is in Carrier Code. '
        'Packs of this type are refused before sending to another carrier.',
    )

    def _neoship_size_category(self):
        if self.package_carrier_type != const.DELIVERY_TYPE:
            return False
        return self.shipper_package_code or False
