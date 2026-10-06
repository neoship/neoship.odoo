from odoo import api, fields, models
from odoo.exceptions import UserError

from .. import const


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    neoship_parcelshop_id = fields.Char(
        string='Neoship Pickup Point ID',
        copy=False,
        help='Pickup point ID sent by the e-shop. Neoship shipments of this order go to this pickup point.',
    )
    neoship_shipment_count = fields.Integer(compute='_compute_neoship_shipment_count')

    @api.depends('picking_ids.carrier_id.delivery_type', 'picking_ids.carrier_tracking_ref')
    def _compute_neoship_shipment_count(self):
        for order in self:
            order.neoship_shipment_count = len(order._neoship_shipments())

    def _neoship_shipments(self):
        return self.picking_ids.filtered(
            lambda picking: picking.delivery_type == const.DELIVERY_TYPE and picking.carrier_tracking_ref
        )

    def action_view_neoship_shipments(self):
        self.ensure_one()
        list_view = self.env.ref('delivery_neoship.view_picking_neoship_shipment_list')
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Neoship Shipments'),
            'res_model': 'stock.picking',
            'views': [(list_view.id, 'list'), (False, 'form')],
            'domain': [('id', 'in', self._neoship_shipments().ids)],
            'context': {'create': False},
        }

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
