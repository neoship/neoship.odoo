from odoo import fields, models


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    neoship_package_id = fields.Char(string='Neoship Package ID', copy=False, readonly=True)
    neoship_reference = fields.Char(copy=False, readonly=True, index='btree_not_null')
    neoship_status = fields.Char(copy=False, readonly=True)
    neoship_last_sync = fields.Datetime(copy=False, readonly=True)
    neoship_error = fields.Text(copy=False, readonly=True)
    neoship_needs_review = fields.Boolean(copy=False)

    _neoship_reference_uniq = models.Constraint(
        'UNIQUE(neoship_reference)',
        'This Neoship reference is already used by another transfer.',
    )
