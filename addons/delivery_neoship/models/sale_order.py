from odoo import fields, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    neoship_parcelshop_id = fields.Char(
        string='Neoship Pickup Point ID',
        copy=False,
        help='Pickup point ID sent by the e-shop. Neoship shipments of this order go to this pickup point.',
    )

    def _action_cancel(self):
        shipped = self.picking_ids.filtered(
            lambda picking: picking.neoship_package_id and not picking.neoship_cancel_refused
        )
        if shipped:
            raise UserError(
                self.env._(
                    'Cancel the Neoship shipments first (Additional Info → Cancel on the transfer): %s',
                    ', '.join(f'{picking.name} ({picking.carrier_tracking_ref})' for picking in shipped),
                )
            )
        return super()._action_cancel()
