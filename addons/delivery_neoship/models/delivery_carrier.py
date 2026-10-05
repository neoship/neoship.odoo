from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval

from .. import const
from .neoship_api import (
    PROD_URL,
    TEST_URL,
    NeoshipAuthError,
    NeoshipClient,
    NeoshipConnectionError,
    NeoshipError,
    NeoshipTimeout,
)


class DeliveryCarrier(models.Model):
    _inherit = 'delivery.carrier'

    delivery_type = fields.Selection(
        selection_add=[(const.DELIVERY_TYPE, 'Neoship')],
        ondelete={
            const.DELIVERY_TYPE: lambda carriers: carriers.write(
                {
                    'delivery_type': const.ODOO_DELIVERY_TYPE_FIXED,
                    'fixed_price': 0,
                }
            )
        },
    )
    neoship_username = fields.Char(groups='base.group_system')
    neoship_password = fields.Char(groups='base.group_system')
    neoship_shipper_id = fields.Char(string='Neoship Shipper ID')
    neoship_carrier = fields.Char()
    neoship_carrier_type = fields.Char()
    neoship_cod_domain = fields.Char(
        string='Cash on Delivery Orders',
        help=(
            'Sales orders matching this filter are shipped as cash on delivery. '
            'When empty, no order is cash on delivery.'
        ),
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('delivery_type') == const.DELIVERY_TYPE and not vals.get('product_id'):
                vals['product_id'] = self._neoship_create_delivery_product(vals.get('name')).id
        return super().create(vals_list)

    def _neoship_create_delivery_product(self, name):
        return self.env['product.product'].create(
            {
                'name': name or 'Neoship',
                'type': const.ODOO_PRODUCT_TYPE_SERVICE,
                'sale_ok': False,
                'purchase_ok': False,
                'invoice_policy': const.ODOO_INVOICE_POLICY_ORDER,
                'list_price': 0.0,
            }
        )

    def _neoship_client(self):
        self.ensure_one()
        carrier = self.sudo()
        if not carrier.neoship_username or not carrier.neoship_password:
            raise UserError(self.env._('Set the Neoship username and password on delivery method %s.', self.name))
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

    def _neoship_user_error(self, error):
        if isinstance(error, NeoshipTimeout):
            return UserError(self.env._('Neoship did not respond in time. Try again later.'))
        if isinstance(error, NeoshipConnectionError):
            return UserError(self.env._('Cannot connect to Neoship. Check the network connection and try again.'))
        if isinstance(error, NeoshipAuthError):
            return UserError(self.env._('Neoship rejected the login: %s', error))
        return UserError(self.env._('Neoship returned an error: %s', error))

    def action_neoship_test_connection(self):
        self.ensure_one()
        try:
            with self._neoship_client() as client:
                client.login()
        except NeoshipError as e:
            raise self._neoship_user_error(e) from e
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': self.env._('Neoship'),
                'message': self.env._('Connection successful.'),
                'sticky': False,
            },
        }

    def neoship_rate_shipment(self, order):
        return self.fixed_rate_shipment(order)

    def neoship_send_shipping(self, pickings):
        raise UserError(self.env._('Creating Neoship shipments is not implemented yet.'))

    def neoship_get_tracking_link(self, picking):
        return self.fixed_get_tracking_link(picking)

    def neoship_cancel_shipment(self, pickings):
        raise UserError(self.env._('Cancelling Neoship shipments is not implemented yet.'))
