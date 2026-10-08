import json
from dataclasses import asdict
from urllib.parse import quote

from dateutil.relativedelta import relativedelta

from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain
from odoo.tools import float_round
from odoo.tools.safe_eval import datetime, safe_eval

from .. import const
from ..tools import neoship_phone, neoship_same_phone, neoship_shipper_key
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
            except (ValueError, TypeError) as e:
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
            **({'timeout': timeout} if timeout else {}),
        )

    def _neoship_is_cod(self, order):
        self.ensure_one()
        if not self.neoship_cod_domain or not order:
            return False
        domain = safe_eval(self.neoship_cod_domain, self._neoship_cod_eval_context())
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
        return self.env._('Neoship returned an error: %s', error)

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
            }
            for shipper in shippers
        ]
        return self._neoship_open_option_wizard(const.OPTION_KIND_SHIPPER, lines, self.env._('Choose Neoship Carrier'))

    def action_neoship_choose_carrier_type(self):
        return self._neoship_open_carrier_type_wizard()

    def _neoship_open_carrier_type_wizard(self, shipper_id=False, shipper_code=False, shipper_name=False):
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
        changed = self.filtered(lambda carrier: carrier.neoship_shipper_id != (shipper_id or 0))
        self.write(
            {
                'neoship_shipper_id': shipper_id,
                'neoship_shipper_code': code,
                'neoship_shipper_name': name,
                **self._neoship_carrier_type_values(carrier_type, carrier_type_name, carrier_type_country_id),
            }
        )
        return changed._neoship_reset_closure_schedules()

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
            shipments = self._neoship_find_or_create(client, picking, packages)
            parcels = self._neoship_parcels(client, shipments, main.get('count_of_packages', 1))
            tracking_number = ','.join(parcel.tracking_number for parcel in parcels if parcel.tracking_number)
            picking.write(
                {
                    'neoship_package_id': shipments[0].id,
                    'neoship_prod_environment': self.prod_environment,
                    'neoship_reference': main['reference_number'],
                    'neoship_shipment_per_pack': len(shipments) > 1,
                    'neoship_cod_amount': main.get('cod_price', 0.0),
                    'neoship_cancel_refused': False,
                    'neoship_error': False,
                    'neoship_label_id': False,
                    **picking._neoship_tracking_reset_values(),
                }
            )
            picking._neoship_store_parcels(parcels)
            try:
                picking._neoship_attach_label(client, tracking_number)
            except NeoshipError as e:
                message = self.env._('The Neoship label could not be downloaded: %s', e)
                picking.neoship_error = message
                picking.message_post(body=message)
        return {'exact_price': self.fixed_price, 'tracking_number': tracking_number}

    def _neoship_find_or_create(self, client, picking, packages):
        references = [package['reference_number'] for package in packages]
        try:
            existing = client.find_packages(references)
            printed = self._neoship_printed_by_reference(picking, existing)
            changes = {
                reference: self._neoship_shipment_changes(printed[reference], package)
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
            print_type = const.LABEL_PRINT_TYPES.get(neoship_shipper_key(self.neoship_shipper_code))
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

    def _neoship_shipment_changes(self, shipment, package):
        old_shipper = shipment.shipper
        old = self._neoship_match_values(
            asdict(shipment), old_shipper and old_shipper.id, len(shipment.sub_packages) + 1
        )
        new = self._neoship_match_values(package, self.neoship_shipper_id, package.get('count_of_packages'))
        changes = {
            key: (old[key], new[key])
            for key in old
            if key in new and not self._neoship_same_match_value(key, old[key], new[key])
        }
        if 'shipper' in changes:
            changes['shipper'] = (old_shipper.name if old_shipper else '', self.neoship_shipper_name or '')
        return changes

    def _neoship_match_values(self, data, shipper_id, count):
        values = {field: str(data.get(field) or '').strip() for field in const.SHIPMENT_MATCH_FIELDS}
        values.update({field: neoship_phone(data.get(field)) for field in const.SHIPMENT_MATCH_PHONE_FIELDS})
        values['shipper'] = shipper_id
        values['cod_price'] = float_round(
            float(data.get('cod_price') or 0.0), precision_digits=const.COD_PRECISION_DIGITS
        )
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
        tracking_numbers = [ref.strip() for ref in (picking.carrier_tracking_ref or '').split(',') if ref.strip()]
        if not tracking_numbers:
            return False
        base_url = PROD_TRACKING_URL if picking.neoship_prod_environment else TEST_TRACKING_URL
        links = [[number, f'{base_url}{quote(number)}/'] for number in tracking_numbers]
        if len(links) == 1:
            return links[0][1]
        return json.dumps(links)

    def neoship_cancel_shipment(self, pickings):
        refused_pickings = pickings.browse()
        for picking in pickings.filtered('neoship_package_id'):
            refused = []
            try:
                with self._neoship_client(picking.neoship_prod_environment) as client:
                    for package_id, tracking_number in picking._neoship_shipments_to_cancel():
                        try:
                            client.cancel_package(package_id)
                        except NeoshipNotFoundError:
                            refused.append(tracking_number)
            except NeoshipError as e:
                raise self._neoship_user_error(e) from e
            if refused:
                message = self.env._(
                    'Neoship can no longer cancel shipment %s. It was probably already handed over to the carrier.',
                    ', '.join(refused),
                )
                picking.write({'neoship_cancel_refused': True, 'neoship_error': message})
                picking.message_post(body=message)
                refused_pickings |= picking
                continue
            for pack in picking._neoship_sent_packs():
                pack.write(pack._neoship_clear_values())
            picking.write(
                {
                    'neoship_package_id': False,
                    'neoship_shipment_per_pack': False,
                    'neoship_cod_amount': 0.0,
                    'neoship_cancel_refused': False,
                    'neoship_error': False,
                    'neoship_label_id': False,
                    **picking._neoship_tracking_reset_values(),
                }
            )
        return refused_pickings
