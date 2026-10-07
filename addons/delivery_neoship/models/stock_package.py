from odoo import api, fields, models

from .stock_picking import NEOSHIP_STATUS_GROUPS


class StockPackage(models.Model):
    _inherit = 'stock.package'

    neoship_package_id = fields.Integer(string='Neoship Package ID', copy=False, readonly=True)
    neoship_reference = fields.Char(copy=False, readonly=True, index='btree_not_null')
    neoship_tracking_ref = fields.Char(string='Neoship Tracking Number', copy=False, readonly=True)
    neoship_status = fields.Char(copy=False, readonly=True)
    neoship_status_group = fields.Selection(
        NEOSHIP_STATUS_GROUPS,
        string='Neoship Delivery',
        copy=False,
        readonly=True,
    )

    @api.model
    def _neoship_clear_values(self):
        return {
            'neoship_package_id': 0,
            'neoship_reference': False,
            'neoship_tracking_ref': False,
            'neoship_status': False,
            'neoship_status_group': False,
        }
