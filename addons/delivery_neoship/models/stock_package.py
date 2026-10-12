from odoo import fields, models


class StockPackage(models.Model):
    _inherit = 'stock.package'

    neoship_parcel_ids = fields.One2many('neoship.parcel', 'package_id', readonly=True)
