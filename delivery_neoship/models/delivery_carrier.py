import json
from dataclasses import asdict

from dateutil.relativedelta import relativedelta

from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain
from odoo.tools import float_round
from odoo.tools.safe_eval import datetime, safe_eval

from .. import const
from ..tools import neoship_phone, neoship_same_phone, neoship_shipper_key
from .neoship_api import (
    PROD_URL,
    TEST_URL,
    NeoshipAuthError,
    NeoshipClient,
    NeoshipConnectionError,
    NeoshipError,
    NeoshipNotFoundError,
    NeoshipResponseError,
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
    neoship_has_closure = fields.Boolean(compute='_compute_neoship_has_closure', store=True)
    neoship_closure_schedule_count = fields.Integer(compute='_compute_neoship_closure_schedule_count')
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
    neoship_label_format = fields.Char(string='Label Format Code', readonly=True)
    neoship_label_format_name = fields.Char(
        string='Label Format',
        readonly=True,
        help='Format of the shipping labels, from the formats Neoship offers for the carrier. '
        'It is fixed when the shipment is created.',
    )
    neoship_label_format_fallback = fields.Char(
        string='Address Label Format Code',
        readonly=True,
        help='Used for shipments to an address when the label format prints only pickup point shipments.',
    )
    neoship_default_weight = fields.Float(
        digits='Stock Weight',
        help='Used when the delivery order has no weight.',
    )
    neoship_package_type_id = fields.Many2one(
        'stock.package.type',
        string='Default Package Type',
        domain=[('package_carrier_type', '=', const.DELIVERY_TYPE)],
        help='Its size category is sent for parcels without a Neoship package type, '
        'unless it belongs to another Packeta carrier. Without one, Neoship uses the largest size of the carrier.',
    )
    neoship_cod_domain = fields.Char(
        string='Cash on Delivery Orders',
        help=(
            'Sales orders matching this filter are shipped as cash on delivery. '
            'When empty or without conditions, no order is cash on delivery.'
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

    @api.depends('delivery_type', 'neoship_shipper_code')
    def _compute_neoship_has_closure(self):
        for carrier in self:
            carrier.neoship_has_closure = bool(carrier._neoship_closure_action())

    def _compute_neoship_closure_schedule_count(self):
        counts = dict(
            self.env['neoship.closure.schedule']
            .sudo()
            .with_context(active_test=False)
            ._read_group([('carrier_id', 'in', self.ids)], ['carrier_id'], ['__count'])
        )
        for carrier in self:
            carrier.neoship_closure_schedule_count = counts.get(carrier._origin, 0)

    def _neoship_closure_action(self):
        self.ensure_one()
        if self.delivery_type != const.DELIVERY_TYPE:
            return None
        return const.CLOSURE_ACTIONS.get(neoship_shipper_key(self.neoship_shipper_code))

    @api.constrains('neoship_shipper_code', 'neoship_carrier_type')
    def _check_neoship_carrier_type(self):
        for carrier in self:
            if carrier.neoship_has_carrier_type and not carrier.neoship_carrier_type:
                raise ValidationError(
                    self.env._('Choose the Packeta home delivery carrier on delivery method %s.', carrier.name)
                )

    @api.constrains('neoship_cod_domain')
    def _check_neoship_cod_domain(self):
        orders = self.env['sale.order'].sudo()
        for carrier in self.filtered('neoship_cod_domain'):
            try:
                Domain(safe_eval(carrier.neoship_cod_domain, carrier._neoship_cod_eval_context())).validate(orders)
            except (SyntaxError, NameError, ValueError, TypeError, ZeroDivisionError) as e:
                raise ValidationError(
                    self.env._(
                        'The cash on delivery filter on delivery method %(method)s is invalid: %(error)s',
                        method=carrier.name,
                        error=e,
                    )
                ) from e

    def _neoship_ignores_package_count(self):
        self.ensure_one()
        return neoship_shipper_key(self.neoship_shipper_code) in const.SHIPPER_CODES_SHIPMENT_PER_PACK

    def _neoship_numeric_cod_reference(self):
        self.ensure_one()
        return neoship_shipper_key(self.neoship_shipper_code) in const.SHIPPER_CODES_NUMERIC_COD_REFERENCE

    @api.model
    def _neoship_requires_carrier_type(self, shipper_code):
        return neoship_shipper_key(shipper_code) in const.SHIPPER_CODES_WITH_CARRIER_TYPE

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

    def _neoship_client(self, prod_environment=None, timeout=None):
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
            language=self.env.lang,
            **({'timeout': timeout} if timeout else {}),
        )

    def _neoship_is_cod(self, order):
        self.ensure_one()
        if not self.neoship_cod_domain or not order:
            return False
        domain = safe_eval(self.neoship_cod_domain, self._neoship_cod_eval_context())
        # A filter without conditions matches every order, but it looks the same as no filter in the editor.
        if not domain:
            return False
        # Warehouse users cannot read every sale.order field (e.g. transaction_ids); the result must not depend on them.
        return bool(order.sudo().filtered_domain(domain))

    def _neoship_cod_eval_context(self):
        return {
            'uid': self.env.uid,
            'user': self.env.user,
            'context_today': lambda: fields.Date.context_today(self),
            'datetime': datetime,
            'relativedelta': relativedelta,
        }

    def _neoship_error_message(self, error):
        if isinstance(error, NeoshipTimeout):
            return self.env._('Neoship did not respond in time. Try again later.')
        if isinstance(error, NeoshipConnectionError):
            return self.env._('Cannot connect to Neoship. Check the network connection and try again.')
        if isinstance(error, NeoshipAuthError):
            return self.env._('Neoship rejected the login: %s', error)
        if isinstance(error, NeoshipResponseError):
            return self.env._('Neoship returned a response that cannot be processed: %s', error)
        if error.field_errors:
            return self.env._(
                'Neoship rejected the shipment data: %s',
                '; '.join(
                    f'{self._neoship_field_label(field)}: {message}' if field else message
                    for field, message in error.field_errors
                ),
            )
        return self.env._('Neoship returned an error: %s', error)

    def _neoship_address_labels(self):
        return {
            'name': self.env._('name'),
            'company': self.env._('company'),
            'street': self.env._('street'),
            'city': self.env._('city'),
            'zip': self.env._('ZIP'),
            'state_code': self.env._('country'),
            'email': self.env._('email'),
            'phone': self.env._('phone'),
        }

    def _neoship_field_label(self, field):
        labels = {
            'reference_number': self.env._('Reference'),
            'weight': self.env._('Weight'),
            'count_of_packages': self.env._('Number of parcels'),
            'parcelshop': self.env._('Pickup point'),
            'carrier_type': self.env._('Packeta carrier'),
            'cod_price': self.env._('Cash on delivery amount'),
            'cod_currency_code': self.env._('Cash on delivery currency'),
            'cod_reference': self.env._('Cash on delivery reference'),
        }
        if field in labels:
            return labels[field]
        address_labels = self._neoship_address_labels()
        prefix, _sep, key = field.partition('_')
        if key in address_labels and prefix == 'sender':
            return self.env._('Sender %s', address_labels[key])
        if key in address_labels and prefix == 'receiver':
            return self.env._('Recipient %s', address_labels[key])
        return field

    def _neoship_user_error(self, error):
        return UserError(self._neoship_error_message(error))

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
        shippers = self._neoship_fetch(lambda client: client.get_active_shippers())
        if not shippers:
            raise UserError(self.env._('No carriers are connected to this Neoship account.'))
        lines = [
            {
                'value': shipper.id,
                'name': shipper.name,
                'code': shipper.shortcut,
                'supports_parcelshops': const.SHIPPER_DELIVERY_TYPE_PARCELSHOP in shipper.delivery_types,
                'print_formats': [asdict(print_format) for print_format in shipper.print_formats],
            }
            for shipper in shippers
        ]
        return self._neoship_open_option_wizard(const.OPTION_KIND_SHIPPER, lines, self.env._('Choose Neoship Carrier'))

    def action_neoship_choose_carrier_type(self):
        return self._neoship_open_carrier_type_wizard()

    def _neoship_open_carrier_type_wizard(
        self, shipper_id=False, shipper_code=False, shipper_name=False, print_formats=None
    ):
        carriers = self._neoship_fetch(lambda client: client.get_packeta_carriers())
        countries = self.env['res.country'].search([('code', 'in', [carrier.state_code for carrier in carriers])])
        country_ids = {country.code: country.id for country in countries}
        lines = [
            {
                'value': carrier.packeta_id,
                'name': carrier.name,
                'country_id': country_ids.get(carrier.state_code, False),
                'currency': carrier.currency,
            }
            for carrier in carriers
        ]
        return self._neoship_open_option_wizard(
            const.OPTION_KIND_CARRIER_TYPE,
            lines,
            self.env._('Choose Packeta Home Delivery Carrier'),
            {
                'shipper_id': shipper_id,
                'shipper_code': shipper_code,
                'shipper_name': shipper_name,
                'print_formats': print_formats,
            },
        )

    def action_neoship_load_package_types(self):
        carriers = self._neoship_fetch(lambda client: client.get_packeta_carriers())
        package_types = self.env['stock.package.type']
        managed = package_types.search(
            [('package_carrier_type', '=', const.DELIVERY_TYPE), ('neoship_carrier_type', '!=', 0)]
        )
        existing = {(item.neoship_carrier_type, item.shipper_package_code): item for item in managed}
        cm = self.env.ref(const.ODOO_UOM_CM)
        length_uom = self.env['product.template']._get_length_uom_id_from_ir_config_parameter()
        loaded_ids = set()
        for carrier in carriers:
            for category in carrier.size_categories:
                key = (carrier.packeta_id, category.code)
                values = {
                    'packaging_length': cm._compute_quantity(category.length, length_uom, round=False),
                    'width': cm._compute_quantity(category.width, length_uom, round=False),
                    'height': cm._compute_quantity(category.height, length_uom, round=False),
                }
                package_type = existing.get(key)
                if package_type:
                    package_type.write(values)
                else:
                    package_type = existing[key] = package_types.create(
                        {
                            **values,
                            'name': f'{carrier.name} {category.code}',
                            'package_carrier_type': const.DELIVERY_TYPE,
                            'neoship_carrier_type': carrier.packeta_id,
                            'shipper_package_code': category.code,
                        }
                    )
                loaded_ids.add(package_type.id)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': self.env._('Neoship'),
                'message': self.env._('%s package types of Packeta carriers are ready.', len(loaded_ids)),
                'sticky': False,
            },
        }

    def action_neoship_choose_label_format(self):
        self.ensure_one()
        if not self.neoship_shipper_id:
            raise UserError(self.env._('Choose the Neoship carrier on delivery method %s.', self.name))
        shippers = self._neoship_fetch(lambda client: client.get_active_shippers())
        shipper = next((shipper for shipper in shippers if shipper.id == self.neoship_shipper_id), None)
        if not shipper or not shipper.print_formats:
            raise UserError(
                self.env._('Neoship offers no label formats for carrier %s.', self.neoship_shipper_name or self.name)
            )
        print_formats = [asdict(print_format) for print_format in shipper.print_formats]
        lines = [
            {
                'sequence': index,
                'value': index,
                'name': print_format['name'],
                'code': print_format['code'],
                'pickup_point_only': print_format['pickup_point_only'],
            }
            for index, print_format in enumerate(print_formats)
        ]
        return self._neoship_open_option_wizard(
            const.OPTION_KIND_LABEL_FORMAT,
            lines,
            self.env._('Choose Label Format'),
            {'print_formats': print_formats},
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
        self,
        shipper_id,
        code,
        name,
        carrier_type=False,
        carrier_type_name=False,
        carrier_type_country_id=False,
        print_formats=None,
    ):
        changed = self.filtered(lambda carrier: carrier.neoship_shipper_id != (shipper_id or 0))
        for carrier in self:
            carrier.write(
                {
                    'neoship_shipper_id': shipper_id,
                    'neoship_shipper_code': code,
                    'neoship_shipper_name': name,
                    **self._neoship_carrier_type_values(carrier_type, carrier_type_name, carrier_type_country_id),
                    **self._neoship_label_format_values(print_formats, carrier.neoship_label_format),
                }
            )
        return changed._neoship_reset_closure_schedules()

    @api.model
    def _neoship_label_format_values(self, print_formats, code=False):
        print_formats = print_formats or []
        address_format = next((item for item in print_formats if not item['pickup_point_only']), None)
        chosen = next((item for item in print_formats if item['code'] == code), None) or address_format
        return {
            'neoship_label_format': chosen['code'] if chosen else False,
            'neoship_label_format_name': chosen['name'] if chosen else False,
            'neoship_label_format_fallback': (
                address_format['code'] if chosen and chosen['pickup_point_only'] and address_format else False
            ),
        }

    def _neoship_print_type(self, pickup_point):
        self.ensure_one()
        if self.neoship_label_format_fallback and not pickup_point:
            return self.neoship_label_format_fallback
        return self.neoship_label_format or None

    def _neoship_reset_closure_schedules(self):
        schedules = self.env['neoship.closure.schedule'].sudo().with_context(active_test=False)
        schedules.search([('carrier_id', 'in', self.ids), ('active', '=', True)]).action_archive()
        created = schedules.browse()
        for carrier in self.filtered('neoship_has_closure'):
            if not schedules.search_count([('carrier_id', 'in', carrier._neoship_same_shipper_account().ids)], limit=1):
                created |= schedules.create({'carrier_id': carrier.id, 'active': False})
        return created

    def _neoship_same_shipper_account(self):
        self.ensure_one()
        carrier = self.sudo()
        shipper_key = neoship_shipper_key(carrier.neoship_shipper_code)
        return (
            carrier.with_context(active_test=False)
            .search(
                [
                    ('delivery_type', '=', const.DELIVERY_TYPE),
                    ('neoship_username', '=', carrier.neoship_username),
                    ('prod_environment', '=', carrier.prod_environment),
                ]
            )
            .filtered(lambda other: neoship_shipper_key(other.neoship_shipper_code) == shipper_key)
        )

    def _neoship_closure_schedule_notification(self, schedules):
        if not schedules:
            return {'type': 'ir.actions.act_window_close'}
        carriers = ', '.join(schedules.carrier_id.mapped('name'))
        params = {
            'type': 'info',
            'title': self.env._('Neoship'),
            'message': self.env._(
                'An archived Neoship closure schedule was created for %s. '
                'An administrator checks its time and days and activates it in '
                'Inventory > Configuration > Neoship Closure Schedules.',
                carriers,
            ),
            'sticky': True,
            'next': {'type': 'ir.actions.act_window_close'},
        }
        if self.env.user.has_group('base.group_system'):
            url = '/odoo/action-delivery_neoship.action_neoship_closure_schedule'
            if len(schedules) == 1:
                url = f'{url}/{schedules.id}'
            params.update(
                {
                    # The browser replaces %s with the link, so % in carrier names is escaped.
                    'message': self.env._(
                        'An archived Neoship closure schedule was created for %(carriers)s. '
                        'Check its time and days, then activate it: %(link)s',
                        carriers=carriers.replace('%', '%%'),
                        link='%s',
                    ),
                    'links': [{'label': self.env._('Open closure schedule'), 'url': url}],
                }
            )
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': params}

    def action_neoship_view_closure_schedules(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('delivery_neoship.action_neoship_closure_schedule')
        action['domain'] = [('carrier_id', '=', self.id)]
        action['context'] = {'active_test': False, 'default_carrier_id': self.id}
        return action

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
        packages = picking._neoship_prepare_packages()
        main = packages[0]
        picking._neoship_check_references_free(packages)
        with self._neoship_client() as client:
            currency = self._neoship_set_cod_currency(client, picking, packages)
            shipments = self._neoship_find_or_create(client, picking, packages, currency)
            parcels = self._neoship_parcels(client, shipments, main.get('count_of_packages', 1))
            tracking_number = ','.join(parcel.tracking_number for parcel in parcels if parcel.tracking_number)
            picking._neoship_store_parcels(packages, parcels, self.prod_environment, currency)
            try:
                picking._neoship_attach_label(client, tracking_number)
            except NeoshipError as e:
                message = self.env._('The Neoship label could not be downloaded: %s', e)
                picking._neoship_main_parcel().error = message
                picking.message_post(body=message)
            picking.neoship_parcel_ids._sync_created(client, self)
        return {'exact_price': self.fixed_price, 'tracking_number': tracking_number}

    def _neoship_set_cod_currency(self, client, picking, packages):
        currency = picking._neoship_cod_currency()
        cod_packages = [package for package in packages if package.get('cod_price')]
        if not cod_packages:
            return currency
        # Neoship stores the amount under the currency it allows for the country without converting it.
        try:
            allowed = client.get_cod_currency_codes(self.neoship_shipper_id, cod_packages[0]['receiver_state_code'])
        except NeoshipError as e:
            raise self._neoship_user_error(e) from e
        if currency.name in allowed:
            return currency
        if not allowed:
            raise UserError(
                self.env._(
                    'Neoship carrier %(carrier)s does not collect cash on delivery in %(country)s. '
                    'Send transfer %(transfer)s without cash on delivery or use another delivery method.',
                    carrier=self.neoship_shipper_name,
                    country=picking.partner_id.country_id.name,
                    transfer=picking.name,
                )
            )
        return picking._neoship_convert_cod(cod_packages, currency, allowed[0])

    def _neoship_find_or_create(self, client, picking, packages, currency):
        references = [package['reference_number'] for package in packages]
        try:
            existing = client.find_packages(references)
            printed = self._neoship_printed_by_reference(picking, existing)
            changes = {
                reference: self._neoship_shipment_changes(printed[reference], package, currency)
                for reference, package in zip(references, packages, strict=True)
                if reference in printed
            }
            if len(printed) == len(packages) and not any(changes.values()):
                return self._neoship_link_existing(picking, [printed[reference] for reference in references])
            self._neoship_discard_existing(client, picking, existing, printed, changes)
        except NeoshipError as e:
            raise self._neoship_user_error(e) from e

        shipments = self._neoship_create(client, packages)
        self._neoship_check_created(packages, shipments)
        self._neoship_check_stored_cod(client, picking, packages, shipments, currency)
        if printed:
            self._neoship_post_replaced(picking, printed, changes, shipments)
        return shipments

    def _neoship_printed_by_reference(self, picking, shipments):
        printed = {}
        for shipment in shipments:
            if shipment.tracking_number:
                printed.setdefault(shipment.reference_number, []).append(shipment)
        duplicates = {reference: group for reference, group in printed.items() if len(group) > 1}
        if duplicates:
            raise UserError(
                self.env._(
                    'Several Neoship shipments use reference %(reference)s (IDs %(ids)s). '
                    'Check them in Neoship before sending transfer %(transfer)s again.',
                    reference=', '.join(str(reference) for reference in duplicates),
                    ids=', '.join(str(shipment.id) for group in duplicates.values() for shipment in group),
                    transfer=picking.name,
                )
            )
        return {reference: group[0] for reference, group in printed.items()}

    def _neoship_link_existing(self, picking, shipments):
        picking.message_post(
            body=self.env._(
                'Existing Neoship shipment %s was found by its reference and linked to this transfer.',
                ', '.join(shipment.tracking_number for shipment in shipments),
            )
        )
        return shipments

    def _neoship_discard_existing(self, client, picking, existing, printed, changes):
        for reference, shipment in printed.items():
            self._neoship_cancel_changed_shipment(client, picking, shipment, changes.get(reference))
        for shipment in existing:
            if not shipment.tracking_number:
                client.delete_package(shipment.id)

    def _neoship_check_created(self, packages, shipments):
        failed = [
            (package, shipment)
            for package, shipment in zip(packages, shipments, strict=True)
            if not shipment.tracking_number
        ]
        if not failed:
            return
        failed_references = ', '.join(package['reference_number'] for package, _shipment in failed)
        carrier_errors = '; '.join(error for _package, shipment in failed for error in shipment.errors)
        if carrier_errors:
            raise UserError(
                self.env._(
                    'The carrier refused Neoship shipment %(reference)s: %(errors)s. '
                    'Fix the problem and validate again.',
                    reference=failed_references,
                    errors=carrier_errors,
                )
            )
        raise UserError(
            self.env._(
                'Neoship created shipment %s but the carrier returned no tracking number. '
                'Fix the problem reported by the carrier and validate again.',
                failed_references,
            )
        )

    def _neoship_check_stored_cod(self, client, picking, packages, shipments, currency):
        for package, shipment in zip(packages, shipments, strict=True):
            if not package.get('cod_price'):
                continue
            try:
                stored = client.get_package(shipment.id)
            except NeoshipError as e:
                raise UserError(
                    self.env._(
                        'Neoship created shipment %(tracking)s for transfer %(transfer)s, but its cash on delivery '
                        'could not be checked: %(error)s. Validate again: the shipment is found by its reference '
                        'and checked.',
                        tracking=shipment.tracking_number,
                        transfer=picking.name,
                        error=self._neoship_error_message(e),
                    )
                ) from e
            if stored.cod_currency_code != package['cod_currency_code'] or currency.compare_amounts(
                stored.cod_price or 0.0, package['cod_price']
            ):
                self._neoship_cancel_wrong_cod(client, picking, shipments, package, stored)

    def _neoship_cancel_wrong_cod(self, client, picking, shipments, package, stored):
        values = {
            'stored': f'{stored.cod_price} {stored.cod_currency_code}',
            'sent': f'{package["cod_price"]} {package["cod_currency_code"]}',
            'transfer': picking.name,
            'tracking': ', '.join(shipment.tracking_number for shipment in shipments),
        }
        try:
            for shipment in shipments:
                client.cancel_package(shipment.id)
        except NeoshipError as e:
            raise UserError(
                self.env._(
                    'Neoship stored cash on delivery %(stored)s instead of %(sent)s for transfer %(transfer)s '
                    'and shipment %(tracking)s could not be cancelled: %(error)s. Cancel it in Neoship.',
                    error=self._neoship_error_message(e),
                    **values,
                )
            ) from e
        raise UserError(
            self.env._(
                'Neoship stored cash on delivery %(stored)s instead of %(sent)s for transfer %(transfer)s, '
                'so shipment %(tracking)s was cancelled. Ask Neoship which currency carrier %(carrier)s collects in.',
                carrier=self.neoship_shipper_name,
                **values,
            )
        )

    def _neoship_post_replaced(self, picking, printed, changes, shipments):
        old_tracking = ', '.join(shipment.tracking_number for shipment in printed.values())
        new_tracking = ', '.join(shipment.tracking_number for shipment in shipments)
        all_changes = '; '.join(self._neoship_format_changes(change) for change in changes.values() if change)
        if all_changes:
            message = self.env._(
                'Neoship shipment %(old)s had different data (%(changes)s), '
                'so it was cancelled and replaced by shipment %(new)s.',
                old=old_tracking,
                changes=all_changes,
                new=new_tracking,
            )
        else:
            message = self.env._(
                'Neoship shipment %(old)s was cancelled and created again together with the missing parcels '
                'as %(new)s.',
                old=old_tracking,
                new=new_tracking,
            )
        picking.message_post(body=message)

    def _neoship_parcels(self, client, shipments, count):
        if len(shipments) > 1 or count < 2:
            return shipments
        try:
            copies = client.get_package(shipments[0].id).sub_packages
        except NeoshipError as e:
            raise self._neoship_user_error(e) from e
        return [shipments[0], *copies]

    def _neoship_create(self, client, packages):
        try:
            print_type = self._neoship_print_type(bool(packages[0].get('parcelshop')))
            return client.create_packages(self.neoship_shipper_id, packages, print_type)
        except NeoshipTimeout as e:
            raise UserError(
                self.env._(
                    'Neoship did not confirm shipment %s in time; it may still be created. '
                    'Wait a minute and validate again: an existing shipment is found by its reference, '
                    'so no duplicate is created.',
                    packages[0]['reference_number'],
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

    def _neoship_shipment_changes(self, shipment, package, currency):
        old_shipper = shipment.shipper
        old = self._neoship_match_values(
            asdict(shipment), old_shipper and old_shipper.id, len(shipment.sub_packages) + 1, currency
        )
        new = self._neoship_match_values(package, self.neoship_shipper_id, package.get('count_of_packages'), currency)
        changes = {
            key: (old[key], new[key])
            for key in old
            if key in new and not self._neoship_same_match_value(key, old[key], new[key])
        }
        if 'shipper' in changes:
            changes['shipper'] = (old_shipper.name if old_shipper else '', self.neoship_shipper_name or '')
        return changes

    def _neoship_match_values(self, data, shipper_id, count, currency):
        values = {field: str(data.get(field) or '').strip() for field in const.SHIPMENT_MATCH_FIELDS}
        values.update({field: neoship_phone(data.get(field)) for field in const.SHIPMENT_MATCH_PHONE_FIELDS})
        values['shipper'] = shipper_id
        values['cod_price'] = currency.round(float(data.get('cod_price') or 0.0))
        # Neoship keeps no weight for carriers that do not use it.
        if data.get('weight') is not None:
            values['weight'] = float_round(float(data['weight']), precision_digits=const.WEIGHT_PRECISION_DIGITS)
        if count:
            values['count_of_packages'] = count
        return values

    def _neoship_same_match_value(self, key, old, new):
        if key in const.SHIPMENT_MATCH_PHONE_FIELDS:
            return neoship_same_phone(old, new)
        return old == new

    def _neoship_format_changes(self, changes):
        return '; '.join(f'{key}: {old} → {new}' for key, (old, new) in changes.items())

    def _neoship_cancel_changed_shipment(self, client, picking, shipment, changes):
        try:
            client.cancel_package(shipment.id)
        except NeoshipNotFoundError as e:
            if not changes:
                raise UserError(
                    self.env._(
                        'Neoship shipment %(tracking)s for transfer %(transfer)s has to be created again together '
                        'with its other parcels, but it can no longer be cancelled because the carrier already '
                        'has it. Check it in Neoship.',
                        tracking=shipment.tracking_number,
                        transfer=picking.name,
                    )
                ) from e
            raise UserError(
                self.env._(
                    'Neoship shipment %(tracking)s for transfer %(transfer)s has different data (%(changes)s) '
                    'and can no longer be cancelled because the carrier already has it. Check it in Neoship.',
                    tracking=shipment.tracking_number,
                    transfer=picking.name,
                    changes=self._neoship_format_changes(changes),
                )
            ) from e

    def neoship_get_tracking_link(self, picking):
        parcels = picking.neoship_parcel_ids.filtered('tracking_ref')
        links = [[parcel.tracking_ref, parcel._tracking_url()] for parcel in parcels]
        if not links:
            return False
        if len(links) == 1:
            return links[0][1]
        return json.dumps(links)

    def neoship_cancel_shipment(self, pickings):
        refused_pickings = pickings.browse()
        for picking in pickings.filtered('neoship_parcel_ids'):
            parcels = picking.neoship_parcel_ids
            cancelled = refused = parcels.browse()
            try:
                with self._neoship_client(parcels[:1].prod_environment) as client:
                    for parcel in parcels.filtered(lambda parcel: not parcel.is_copy):
                        try:
                            client.cancel_package(parcel.neoship_id)
                        except NeoshipNotFoundError:
                            refused |= parcel
                        else:
                            cancelled |= parcel
            except NeoshipError as e:
                raise self._neoship_user_error(e) from e
            if not refused:
                parcels.unlink()
                continue
            cancelled.unlink()
            for parcel in refused:
                message = self._neoship_cancel_refused_message(parcel.tracking_ref)
                parcel.write({'cancel_refused': True, 'error': message})
            picking.carrier_tracking_ref = ','.join(picking.neoship_parcel_ids.mapped('tracking_ref'))
            picking.message_post(body=self._neoship_cancel_refused_message(', '.join(refused.mapped('tracking_ref'))))
            refused_pickings |= picking
        return refused_pickings

    def _neoship_cancel_refused_message(self, tracking):
        return self.env._(
            'Neoship can no longer cancel shipment %s. It was probably already handed over to the carrier.',
            tracking,
        )
