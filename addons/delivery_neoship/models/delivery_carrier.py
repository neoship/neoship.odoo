from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval

from .neoship_api import PROD_URL, TEST_URL, NeoshipClient, NeoshipError


class DeliveryCarrier(models.Model):
    _inherit = 'delivery.carrier'

    delivery_type = fields.Selection(
        selection_add=[('neoship', 'Neoship')],
        ondelete={'neoship': lambda carriers: carriers.write({'delivery_type': 'fixed', 'fixed_price': 0})},
    )
    neoship_username = fields.Char(string='Neoship Username', groups='base.group_system')
    neoship_password = fields.Char(string='Neoship Password', groups='base.group_system')
    neoship_shipper_id = fields.Char(string='Neoship Shipper ID')
    neoship_carrier = fields.Char(string='Neoship Carrier')
    neoship_carrier_type = fields.Char(string='Neoship Carrier Type')
    neoship_cod_domain = fields.Char(
        string='Cash on Delivery Orders',
        help='Sales orders matching this filter are shipped as cash on delivery. '
             'When empty, no order is cash on delivery.',
    )

    def _neoship_client(self):
        self.ensure_one()
        carrier = self.sudo()
        if not carrier.neoship_username or not carrier.neoship_password:
            raise UserError(_('Set the Neoship username and password on delivery method %s.', self.name))
        return NeoshipClient(
            PROD_URL if self.prod_environment else TEST_URL,
            carrier.neoship_username,
            carrier.neoship_password,
        )

    def _neoship_is_cod(self, order):
        self.ensure_one()
        if not self.neoship_cod_domain or not order:
            return False
        domain = safe_eval(self.neoship_cod_domain)
        return bool(order.filtered_domain(domain))

    def action_neoship_test_connection(self):
        self.ensure_one()
        try:
            self._neoship_client().login()
        except NeoshipError as e:
            raise UserError(_('Neoship connection failed: %s', e)) from e
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _('Neoship'),
                'message': _('Connection successful.'),
                'sticky': False,
            },
        }

    def neoship_rate_shipment(self, order):
        return self.fixed_rate_shipment(order)

    def neoship_send_shipping(self, pickings):
        raise UserError(_('Creating Neoship shipments is not implemented yet.'))

    def neoship_get_tracking_link(self, picking):
        return self.fixed_get_tracking_link(picking)

    def neoship_cancel_shipment(self, pickings):
        raise UserError(_('Cancelling Neoship shipments is not implemented yet.'))
