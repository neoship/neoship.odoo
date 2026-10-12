from odoo import api, fields, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    neoship_parcelshop_id = fields.Char(
        string='Neoship Pickup Point ID',
        copy=False,
        help='Pickup point ID sent by the e-shop. Neoship shipments of this order go to this pickup point.',
    )
    neoship_parcel_count = fields.Integer(compute='_compute_neoship_parcel_count')

    @api.depends('picking_ids.neoship_parcel_ids')
    def _compute_neoship_parcel_count(self):
        for order in self:
            order.neoship_parcel_count = len(order.picking_ids.neoship_parcel_ids)

    def action_view_neoship_parcels(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Neoship Parcels'),
            'res_model': 'neoship.parcel',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [('picking_id', 'in', self.picking_ids.ids)],
            'context': {'create': False},
        }

    def _action_cancel(self):
        shipped = self.picking_ids.neoship_parcel_ids.filtered(lambda parcel: not parcel.cancel_refused).picking_id
        if shipped:
            raise UserError(
                self.env._(
                    'Cancel the Neoship shipments first (Additional Info → Cancel on the transfer): %s',
                    ', '.join(f'{picking.name} ({picking.carrier_tracking_ref})' for picking in shipped),
                )
            )
        return super()._action_cancel()
