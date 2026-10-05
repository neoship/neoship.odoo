from odoo import fields, models


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    neoship_package_id = fields.Char(string='Neoship Package ID', copy=False, readonly=True)
    neoship_reference = fields.Char(string='Neoship Reference', copy=False, readonly=True, index='btree_not_null')
    neoship_status = fields.Char(string='Neoship Status', copy=False, readonly=True)
    neoship_last_sync = fields.Datetime(string='Neoship Last Sync', copy=False, readonly=True)
    neoship_error = fields.Text(string='Neoship Error', copy=False, readonly=True)
    neoship_needs_review = fields.Boolean(string='Neoship Needs Review', copy=False)

    _neoship_reference_uniq = models.Constraint(
        'UNIQUE(neoship_reference)',
        'This Neoship reference is already used by another transfer.',
    )
