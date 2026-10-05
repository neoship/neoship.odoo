import json
from urllib.parse import quote

from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.safe_eval import safe_eval

from .. import const
from .neoship_api import (
    PROD_TRACKING_URL,
    PROD_URL,
    TEST_TRACKING_URL,
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
    neoship_shipper_id = fields.Integer(string='Neoship Carrier ID', readonly=True)
    neoship_shipper_code = fields.Char(string='Neoship Carrier Code', readonly=True)
    neoship_shipper_name = fields.Char(string='Neoship Carrier', readonly=True)
    neoship_has_carrier_type = fields.Boolean(compute='_compute_neoship_has_carrier_type')
    neoship_carrier_type = fields.Integer(string='Packeta Home Delivery Carrier ID', readonly=True)
    neoship_carrier_type_name = fields.Char(
        string='Packeta Home Delivery Carrier',
        readonly=True,
        help='Packeta carrier used for delivery to an address. Pickup point orders go to the pickup point.',
    )
    neoship_default_weight = fields.Float(
        digits='Stock Weight',
        help='Used when the delivery order has no weight.',
    )
    neoship_cod_domain = fields.Char(
        string='Cash on Delivery Orders',
        help=(
            'Sales orders matching this filter are shipped as cash on delivery. '
            'When empty, no order is cash on delivery.'
        ),
    )

    _neoship_default_weight_positive = models.Constraint(
        'CHECK(neoship_default_weight >= 0)',
        'The Neoship default weight cannot be negative.',
    )

    @api.depends('neoship_shipper_code')
    def _compute_neoship_has_carrier_type(self):
        for carrier in self:
            carrier.neoship_has_carrier_type = self._neoship_requires_carrier_type(carrier.neoship_shipper_code)

    @api.constrains('neoship_shipper_code', 'neoship_carrier_type')
    def _check_neoship_carrier_type(self):
        for carrier in self:
            if carrier.neoship_has_carrier_type and not carrier.neoship_carrier_type:
                raise ValidationError(
                    self.env._('Choose the Packeta home delivery carrier on delivery method %s.', carrier.name)
                )

    @api.model
    def _neoship_requires_carrier_type(self, shipper_code):
        return (shipper_code or '').lower() in const.SHIPPER_CODES_WITH_CARRIER_TYPE

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('delivery_type') == const.DELIVERY_TYPE and not vals.get('product_id'):
                vals['product_id'] = self._neoship_create_delivery_product(vals.get('name')).id
        return super().create(vals_list)

    def write(self, vals):
        switched = self.browse()
        if 'prod_environment' in vals:
            switched = self.filtered(
                lambda carrier: (
                    carrier.delivery_type == const.DELIVERY_TYPE
                    and carrier.prod_environment != bool(vals['prod_environment'])
                )
            )
        result = super().write(vals)
        if switched:
            switched._neoship_set_shipper(False, False, False)
        return result

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

    def action_neoship_choose_shipper(self):
        shippers = self._neoship_fetch(lambda client: client.get_shippers())
        lines = [
            {
                'value': shipper['id'],
                'name': shipper['name'],
                'code': shipper['shortcut'],
                'supports_parcelshops': shipper.get('supports_parcelshops', False),
            }
            for shipper in shippers
        ]
        return self._neoship_open_option_wizard(const.OPTION_KIND_SHIPPER, lines, self.env._('Choose Neoship Carrier'))

    def action_neoship_choose_carrier_type(self):
        return self._neoship_open_carrier_type_wizard()

    def _neoship_open_carrier_type_wizard(self, shipper_id=False, shipper_code=False, shipper_name=False):
        carriers = self._neoship_fetch(lambda client: client.get_packeta_carriers())
        lines = [
            {
                'value': carrier['packeta_id'],
                'name': carrier['name'],
                'country': carrier.get('state'),
                'currency': carrier.get('currency'),
            }
            for carrier in carriers
        ]
        return self._neoship_open_option_wizard(
            const.OPTION_KIND_CARRIER_TYPE,
            lines,
            self.env._('Choose Packeta Home Delivery Carrier'),
            {'shipper_id': shipper_id, 'shipper_code': shipper_code, 'shipper_name': shipper_name},
        )

    def _neoship_fetch(self, call):
        self.ensure_one()
        try:
            with self._neoship_client() as client:
                return call(client)
        except NeoshipError as e:
            raise self._neoship_user_error(e) from e

    def _neoship_open_option_wizard(self, kind, lines, title, wizard_vals=None):
        wizard = self.env['neoship.option.wizard'].create(
            {
                **(wizard_vals or {}),
                'carrier_id': self.id,
                'kind': kind,
                'line_ids': [Command.create(line) for line in lines],
            }
        )
        return {
            'type': 'ir.actions.act_window',
            'name': title,
            'res_model': 'neoship.option.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _neoship_set_shipper(self, shipper_id, code, name, carrier_type=False, carrier_type_name=False):
        self.write(
            {
                'neoship_shipper_id': shipper_id,
                'neoship_shipper_code': code,
                'neoship_shipper_name': name,
                'neoship_carrier_type': carrier_type,
                'neoship_carrier_type_name': carrier_type_name,
            }
        )

    def _neoship_set_carrier_type(self, carrier_type, name):
        self.write({'neoship_carrier_type': carrier_type, 'neoship_carrier_type_name': name})

    def neoship_rate_shipment(self, order):
        return self.fixed_rate_shipment(order)

    def neoship_send_shipping(self, pickings):
        raise UserError(self.env._('Creating Neoship shipments is not implemented yet.'))

    def neoship_get_tracking_link(self, picking):
        tracking_numbers = [ref.strip() for ref in (picking.carrier_tracking_ref or '').split(',') if ref.strip()]
        if not tracking_numbers:
            return False
        base_url = PROD_TRACKING_URL if self.prod_environment else TEST_TRACKING_URL
        links = [[number, f'{base_url}{quote(number)}/'] for number in tracking_numbers]
        if len(links) == 1:
            return links[0][1]
        return json.dumps(links)

    def neoship_cancel_shipment(self, pickings):
        raise UserError(self.env._('Cancelling Neoship shipments is not implemented yet.'))
