import json
from urllib.parse import quote

from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare
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
    NeoshipNotFoundError,
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
    neoship_carrier_type_country_id = fields.Many2one(
        'res.country',
        string='Packeta Home Delivery Country',
        readonly=True,
        help='Country of the Packeta home delivery carrier. Recipients in other countries are refused before sending.',
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

    def _neoship_client(self, prod_environment=None):
        self.ensure_one()
        carrier = self.sudo()
        if not carrier.neoship_username or not carrier.neoship_password:
            raise UserError(self.env._('Set the Neoship username and password on delivery method %s.', self.name))
        if prod_environment is None:
            prod_environment = self.prod_environment
        return NeoshipClient(
            PROD_URL if prod_environment else TEST_URL,
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
        countries = self.env['res.country'].search([('code', 'in', [carrier['state_code'] for carrier in carriers])])
        country_ids = {country.code: country.id for country in countries}
        lines = [
            {
                'value': carrier['packeta_id'],
                'name': carrier['name'],
                'country_id': country_ids.get(carrier['state_code'], False),
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

    def _neoship_fetch(self, call, prod_environment=None):
        self.ensure_one()
        try:
            with self._neoship_client(prod_environment) as client:
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

    def _neoship_set_shipper(
        self, shipper_id, code, name, carrier_type=False, carrier_type_name=False, carrier_type_country_id=False
    ):
        self.write(
            {
                'neoship_shipper_id': shipper_id,
                'neoship_shipper_code': code,
                'neoship_shipper_name': name,
                **self._neoship_carrier_type_values(carrier_type, carrier_type_name, carrier_type_country_id),
            }
        )

    def _neoship_set_carrier_type(self, carrier_type, name, country_id=False):
        self.write(self._neoship_carrier_type_values(carrier_type, name, country_id))

    def _neoship_carrier_type_values(self, carrier_type, name, country_id):
        return {
            'neoship_carrier_type': carrier_type,
            'neoship_carrier_type_name': name,
            'neoship_carrier_type_country_id': country_id,
        }

    def neoship_rate_shipment(self, order):
        return self.fixed_rate_shipment(order)

    def neoship_send_shipping(self, pickings):
        return [self._neoship_send_picking(picking) for picking in pickings]

    def _neoship_send_picking(self, picking):
        self.ensure_one()
        if not self.neoship_shipper_id:
            raise UserError(self.env._('Choose the Neoship carrier on delivery method %s.', self.name))
        picking._neoship_lock()
        package = picking._neoship_prepare_package()
        picking._neoship_check_reference_free(package['reference_number'])
        with self._neoship_client() as client:
            shipment = self._neoship_find_or_create(client, picking, package)
            picking.write(
                {
                    'neoship_package_id': shipment['id'],
                    'neoship_prod_environment': self.prod_environment,
                    'neoship_reference': package['reference_number'],
                    'neoship_cod_amount': package.get('cod_price', 0.0),
                    'neoship_error': False,
                    **picking._neoship_tracking_reset_values(),
                }
            )
            try:
                picking._neoship_attach_label(client, shipment['tracking_number'])
            except NeoshipError as e:
                message = self.env._('The Neoship label could not be downloaded: %s', e)
                picking.neoship_error = message
                picking.message_post(body=message)
        return {'exact_price': self.fixed_price, 'tracking_number': shipment['tracking_number']}

    def _neoship_find_or_create(self, client, picking, package):
        reference = package['reference_number']
        try:
            existing = client.find_packages([reference])
            printed = [shipment for shipment in existing if shipment.get('tracking_number')]
            if len(printed) > 1:
                raise UserError(
                    self.env._(
                        'Several Neoship shipments use reference %(reference)s (IDs %(ids)s). '
                        'Check them in Neoship before sending transfer %(transfer)s again.',
                        reference=reference,
                        ids=', '.join(str(shipment['id']) for shipment in printed),
                        transfer=picking.name,
                    )
                )
            changes = ''
            if printed:
                changes = self._neoship_shipment_changes(printed[0], package)
                if not changes:
                    picking.message_post(
                        body=self.env._(
                            'Existing Neoship shipment %s was found by its reference and linked to this transfer.',
                            printed[0]['tracking_number'],
                        )
                    )
                    return printed[0]
                self._neoship_cancel_changed_shipment(client, picking, printed[0], changes)
            for unprinted in existing:
                if not unprinted.get('tracking_number'):
                    client.delete_package(unprinted['id'])
        except NeoshipError as e:
            raise self._neoship_user_error(e) from e

        shipment = self._neoship_create(client, package)
        if not shipment.get('tracking_number'):
            raise UserError(
                self.env._(
                    'Neoship created shipment %s but the carrier returned no tracking number. '
                    'Fix the problem reported by the carrier and validate again.',
                    reference,
                )
            )
        if printed:
            picking.message_post(
                body=self.env._(
                    'Neoship shipment %(old)s had different data (%(changes)s), '
                    'so it was cancelled and replaced by shipment %(new)s.',
                    old=printed[0]['tracking_number'],
                    changes=changes,
                    new=shipment['tracking_number'],
                )
            )
        return shipment

    def _neoship_create(self, client, package):
        try:
            return client.create_packages(self.neoship_shipper_id, [package])[0]
        except NeoshipTimeout as e:
            raise UserError(
                self.env._(
                    'Neoship did not confirm shipment %s in time; it may still be created. '
                    'Wait a minute and validate again: an existing shipment is found by its reference, '
                    'so no duplicate is created.',
                    package['reference_number'],
                )
            ) from e
        except NeoshipNotFoundError as e:
            raise UserError(
                self.env._(
                    'Neoship carrier %(carrier)s is not in the price list of your Neoship account. '
                    'Choose another carrier on delivery method %(method)s or ask Neoship to add it.',
                    carrier=self.neoship_shipper_name,
                    method=self.name,
                )
            ) from e
        except NeoshipError as e:
            raise self._neoship_user_error(e) from e

    def _neoship_shipment_changes(self, shipment, package):
        changes = [
            f'{field}: {shipment.get(field) or ""} → {package.get(field) or ""}'
            for field in const.SHIPMENT_MATCH_FIELDS
            if str(shipment.get(field) or '').strip() != str(package.get(field) or '').strip()
        ]
        old_cod = float(shipment.get('cod_price') or 0.0)
        new_cod = package.get('cod_price', 0.0)
        if float_compare(old_cod, new_cod, precision_digits=const.COD_PRECISION_DIGITS):
            changes.append(f'cod_price: {old_cod} → {new_cod}')
        return '; '.join(changes)

    def _neoship_cancel_changed_shipment(self, client, picking, shipment, changes):
        try:
            client.cancel_package(shipment['id'])
        except NeoshipNotFoundError as e:
            raise UserError(
                self.env._(
                    'Neoship shipment %(tracking)s for transfer %(transfer)s has different data (%(changes)s) '
                    'and can no longer be cancelled because the carrier already has it. Check it in Neoship.',
                    tracking=shipment['tracking_number'],
                    transfer=picking.name,
                    changes=changes,
                )
            ) from e

    def neoship_get_tracking_link(self, picking):
        tracking_numbers = [ref.strip() for ref in (picking.carrier_tracking_ref or '').split(',') if ref.strip()]
        if not tracking_numbers:
            return False
        base_url = PROD_TRACKING_URL if picking.neoship_prod_environment else TEST_TRACKING_URL
        links = [[number, f'{base_url}{quote(number)}/'] for number in tracking_numbers]
        if len(links) == 1:
            return links[0][1]
        return json.dumps(links)

    def neoship_cancel_shipment(self, pickings):
        for picking in pickings.filtered('neoship_package_id'):
            try:
                with self._neoship_client(picking.neoship_prod_environment) as client:
                    client.cancel_package(picking.neoship_package_id)
            except NeoshipNotFoundError:
                message = self.env._(
                    'Neoship can no longer cancel shipment %s. It was probably already handed over to the carrier.',
                    picking.carrier_tracking_ref,
                )
                picking.write({'neoship_cancel_refused': True, 'neoship_error': message})
                picking.message_post(body=message)
                continue
            except NeoshipError as e:
                raise self._neoship_user_error(e) from e
            picking.write(
                {
                    'neoship_package_id': False,
                    'neoship_cod_amount': 0.0,
                    'neoship_error': False,
                    **picking._neoship_tracking_reset_values(),
                }
            )
