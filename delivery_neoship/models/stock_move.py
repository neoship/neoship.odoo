from odoo import models
from odoo.exceptions import UserError


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _neoship_delivered_quantity(self, sale_line):
        if any(move.product_id != sale_line.product_id for move in self):
            raise UserError(
                self.env._(
                    'Transfer %(transfer)s delivers %(product)s as separate components, so its cash on delivery '
                    'amount cannot be computed. Set the cash on delivery amount manually.',
                    transfer=', '.join(self.picking_id.mapped('name')),
                    product=sale_line.product_id.display_name,
                )
            )
        return sum(
            line.product_uom_id._compute_quantity(line.quantity, sale_line.product_uom_id, round=False)
            for line in self.move_line_ids
        )
