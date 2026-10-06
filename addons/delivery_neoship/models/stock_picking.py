import re

from odoo import api, fields, models
from odoo.exceptions import LockError, UserError
from odoo.tools import float_round, ormcache

from .. import const
from .neoship_api import NeoshipError


def neoship_code(value):
    return re.sub(const.REFERENCE_INVALID_CHARS, '-', value or '').strip('-')[: const.REFERENCE_MAX_LENGTH]


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    neoship_package_id = fields.Integer(string='Neoship Package ID', copy=False, readonly=True)
    neoship_prod_environment = fields.Boolean(string='Neoship Production', copy=False, readonly=True)
    neoship_reference = fields.Char(copy=False, readonly=True, index='btree_not_null')
    neoship_status = fields.Char(copy=False, readonly=True)
    neoship_last_sync = fields.Datetime(copy=False, readonly=True)
    neoship_error = fields.Text(copy=False, readonly=True)
    neoship_needs_review = fields.Boolean(copy=False)
    neoship_cancel_refused = fields.Boolean(
        copy=False,
        readonly=True,
        help='Neoship refused to cancel the shipment because the carrier already has it.',
    )
    neoship_cod_amount = fields.Float(
        string='Neoship Cash on Delivery', digits='Product Price', copy=False, readonly=True
    )
    neoship_cod_manual = fields.Boolean(
        string='Manual Cash on Delivery',
        copy=False,
        help=(
            'Send the amount below instead of the amount computed from the sales order. Zero means no cash on delivery.'
        ),
    )
    neoship_cod_manual_amount = fields.Float(string='Cash on Delivery Amount', digits='Product Price', copy=False)

    _neoship_reference_uniq = models.Constraint(
        'UNIQUE(neoship_reference)',
        'This Neoship reference is already used by another transfer.',
    )
    _neoship_cod_manual_amount_positive = models.Constraint(
        'CHECK(neoship_cod_manual_amount >= 0)',
        'The cash on delivery amount cannot be negative.',
    )

    def _neoship_lock(self):
        try:
            self.lock_for_update()
        except LockError as e:
            raise UserError(
                self.env._('Transfer %s is already being sent to Neoship. Try again in a moment.', self.display_name)
            ) from e

    def _neoship_lock_for_order(self, order):
        try:
            self.lock_for_update()
        except LockError as e:
            raise UserError(
                self.env._(
                    'Another transfer of order %s is being processed. Try again in a moment.',
                    order.name,
                )
            ) from e

    @api.model
    @ormcache()
    def _neoship_multi_company(self):
        # cleared by res.company create/unlink
        return self.env['res.company'].sudo().with_context(active_test=False).search_count([]) > 1

    def _neoship_reference(self):
        self.ensure_one()
        if self._neoship_multi_company():
            return neoship_code(f'{const.REFERENCE_COMPANY_PREFIX}{self.company_id.id}-{self.name}')
        return neoship_code(self.name)

    def _neoship_check_reference_free(self, reference):
        self.ensure_one()
        other = self.sudo().search([('neoship_reference', '=', reference), ('id', '!=', self.id)], limit=1)
        if other:
            raise UserError(
                self.env._(
                    'Neoship reference %(reference)s of transfer %(transfer)s is already used by transfer '
                    '%(other)s (%(company)s).',
                    reference=reference,
                    transfer=self.name,
                    other=other.name,
                    company=other.company_id.name,
                )
            )

    def _neoship_prepare_package(self):
        self.ensure_one()
        carrier = self.carrier_id
        sender = self.picking_type_id.warehouse_id.partner_id or self.company_id.partner_id
        receiver = self.partner_id
        package = {
            'reference_number': self._neoship_reference(),
            **self._neoship_address_values('sender', sender, sender | self.company_id.partner_id),
            **self._neoship_address_values(
                'receiver', receiver, receiver | self.sale_id.partner_id | receiver.commercial_partner_id
            ),
            'count_of_packages': len(self.move_line_ids.result_package_id.outermost_package_id) or 1,
        }
        self._neoship_check_addresses(package, sender, receiver)

        weight = self._neoship_weight_kg()
        if carrier.neoship_has_carrier_type and not 0 < weight <= const.PACKETA_MAX_WEIGHT_KG:
            raise UserError(
                self.env._(
                    'Packeta needs a weight between 0 and %(max)s kg, transfer %(transfer)s has %(weight)s kg.',
                    max=const.PACKETA_MAX_WEIGHT_KG,
                    transfer=self.name,
                    weight=weight,
                )
            )
        if weight > 0:
            package['weight'] = weight

        parcelshop = self.sale_id.neoship_parcelshop_id
        if parcelshop:
            package['parcelshop'] = parcelshop
        elif carrier.neoship_has_carrier_type:
            self._neoship_check_packeta_country(receiver)
            package['carrier_type'] = carrier.neoship_carrier_type

        package.update(self._neoship_cod_values())
        return package

    def _neoship_address_values(self, prefix, partner, contacts):
        commercial = partner.commercial_partner_id
        return {
            f'{prefix}_name': partner.name or commercial.name,
            f'{prefix}_company': commercial.name if commercial.is_company and commercial != partner else '',
            f'{prefix}_street': ', '.join(filter(None, [partner.street, partner.street2])),
            f'{prefix}_city': partner.city,
            f'{prefix}_zip': partner.zip,
            f'{prefix}_state_code': partner.country_id.code,
            f'{prefix}_email': next(iter(contacts.filtered('email').mapped('email')), False),
            f'{prefix}_phone': re.sub(r'\s+', '', next(iter(contacts.filtered('phone').mapped('phone')), '')),
        }

    def _neoship_check_addresses(self, package, sender, receiver):
        labels = {
            'name': self.env._('name'),
            'street': self.env._('street'),
            'city': self.env._('city'),
            'zip': self.env._('ZIP'),
            'state_code': self.env._('country'),
            'email': self.env._('email'),
            'phone': self.env._('phone'),
        }

        def missing(prefix):
            return ', '.join(label for key, label in labels.items() if not package[f'{prefix}_{key}'])

        problems = []
        if missing_sender := missing('sender'):
            problems.append(
                self.env._(
                    'Sender %(partner)s is missing: %(fields)s', partner=sender.display_name, fields=missing_sender
                )
            )
        if missing_receiver := missing('receiver'):
            problems.append(
                self.env._(
                    'Recipient %(partner)s is missing: %(fields)s',
                    partner=receiver.display_name,
                    fields=missing_receiver,
                )
            )
        if problems:
            raise UserError('\n'.join([self.env._('Transfer %s cannot be sent to Neoship.', self.name), *problems]))

    def _neoship_check_packeta_country(self, receiver):
        carrier = self.carrier_id
        country = carrier.neoship_carrier_type_country_id
        if country and receiver.country_id != country:
            raise UserError(
                self.env._(
                    'Packeta carrier %(carrier)s of delivery method %(method)s delivers only to %(country)s, '
                    'but the recipient of transfer %(transfer)s is in %(recipient_country)s. '
                    'Use the delivery method for that country.',
                    carrier=carrier.neoship_carrier_type_name,
                    method=carrier.name,
                    country=country.name,
                    transfer=self.name,
                    recipient_country=receiver.country_id.name,
                )
            )

    def _neoship_weight_kg(self):
        weight = self.shipping_weight or self.weight or self.carrier_id.neoship_default_weight
        weight_uom = self.env['product.template']._get_weight_uom_id_from_ir_config_parameter()
        weight_kg = weight_uom._compute_quantity(weight, self.env.ref(const.ODOO_UOM_KG), round=False)
        return float_round(weight_kg, precision_digits=3)

    def _neoship_cod_values(self):
        order = self.sale_id
        if self.neoship_cod_manual:
            amount = self.neoship_cod_manual_amount
        elif self.carrier_id._neoship_is_cod(order):
            others = order.picking_ids - self
            others.filtered(
                lambda picking: (
                    picking.delivery_type == const.DELIVERY_TYPE and picking.state != const.ODOO_PICKING_STATE_CANCEL
                )
            )._neoship_lock_for_order(order)
            previous = others.filtered('neoship_cod_amount')
            if previous:
                raise UserError(
                    self.env._(
                        'Order %(order)s already has a cash on delivery shipment (%(transfers)s). '
                        'Set the cash on delivery amount on transfer %(transfer)s manually.',
                        order=order.name,
                        transfers=', '.join(previous.mapped('name')),
                        transfer=self.name,
                    )
                )
            amount = order.amount_total
        else:
            return {}
        currency = order.currency_id or self.company_id.currency_id
        if currency.is_zero(amount):
            return {}
        return {
            'cod_price': currency.round(amount),
            'cod_currency_code': currency.name,
            'cod_reference': neoship_code(order.name or self.name),
        }

    def _neoship_attach_label(self, client, tracking_number):
        self.ensure_one()
        label = client.get_label(self.neoship_package_id)
        if not isinstance(label, bytes):
            raise NeoshipError(f'Unexpected label response for package {self.neoship_package_id}')
        name = self._neoship_label_name(tracking_number)
        self.message_post(body=self.env._('Neoship shipping label'), attachments=[(name, label)])

    def _neoship_label_name(self, tracking_number):
        return f'{self.carrier_id._get_delivery_label_prefix()}-{tracking_number}.pdf'

    def _neoship_label(self):
        self.ensure_one()
        return self.env['ir.attachment'].search(
            [
                ('res_model', '=', self._name),
                ('res_id', '=', self.id),
                ('name', '=', self._neoship_label_name(self.carrier_tracking_ref)),
            ],
            order='id desc',
            limit=1,
        )

    def action_neoship_open_label(self):
        self.ensure_one()
        label = self._neoship_label()
        if not label:
            self.action_neoship_download_label()
            label = self._neoship_label()
        return {'type': 'ir.actions.act_url', 'url': f'/web/content/{label.id}', 'target': 'new'}

    def action_neoship_download_label(self):
        self.ensure_one()
        self.carrier_id._neoship_fetch(
            lambda client: self._neoship_attach_label(client, self.carrier_tracking_ref),
            self.neoship_prod_environment,
        )
        self.neoship_error = False

    def cancel_shipment(self):
        neoship = self.filtered(lambda picking: picking.delivery_type == const.DELIVERY_TYPE)
        super(StockPicking, self - neoship).cancel_shipment()
        # Core always reports success and clears the tracking number; a refused cancel must keep both.
        for picking in neoship:
            picking.carrier_id.cancel_shipment(picking)
            if not picking.neoship_cancel_refused:
                picking.message_post(body=self.env._('Shipment %s cancelled', picking.carrier_tracking_ref))
                picking.carrier_tracking_ref = False
        refused = neoship.filtered('neoship_cancel_refused')
        if not refused:
            return None
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'warning',
                'title': self.env._('Neoship'),
                'message': '\n'.join(refused.mapped('neoship_error')),
                'sticky': True,
            },
        }
