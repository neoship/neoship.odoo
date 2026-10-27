from datetime import datetime

from odoo import api, fields, models
from odoo.exceptions import LockError, UserError
from odoo.tools import float_round, format_amount, format_date, ormcache

from .. import const
from ..tools import (
    neoship_code,
    neoship_combined_status_group,
    neoship_digits,
    neoship_parcel_reference,
    neoship_phone,
    neoship_reference,
)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    neoship_parcel_ids = fields.One2many('neoship.parcel', 'picking_id', readonly=True)
    neoship_reference = fields.Char(
        readonly=True,
        copy=False,
        help='Reference of the shipment in Neoship, kept from the first time the transfer was sent.',
    )
    neoship_status = fields.Char(compute='_compute_neoship_status', store=True)
    neoship_status_group = fields.Selection(
        const.STATUS_GROUP_SELECTION,
        string='Neoship Delivery',
        compute='_compute_neoship_status',
        store=True,
        index=True,
    )
    neoship_cod_manual = fields.Boolean(
        string='Manual Cash on Delivery',
        copy=False,
        help=(
            'Send the amount below instead of the amount computed from the products of this transfer. '
            'Zero means no cash on delivery.'
        ),
    )
    neoship_cod_manual_amount = fields.Float(string='Cash on Delivery Amount', digits='Product Price', copy=False)

    _neoship_cod_manual_amount_positive = models.Constraint(
        'CHECK(neoship_cod_manual_amount >= 0)',
        'The cash on delivery amount cannot be negative.',
    )

    @api.depends('neoship_parcel_ids.status', 'neoship_parcel_ids.status_group', 'neoship_parcel_ids.tracking_ref')
    def _compute_neoship_status(self):
        for picking in self:
            parcels = picking.neoship_parcel_ids
            picking.neoship_status_group = (
                neoship_combined_status_group(parcels.mapped('status_group')) if parcels else False
            )
            if len(parcels) > 1:
                statuses = (f'{parcel.tracking_ref}: {parcel.status or "-"}' for parcel in parcels)
                picking.neoship_status = '; '.join(statuses)
            else:
                picking.neoship_status = parcels.status

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
        if self.neoship_reference:
            return self.neoship_reference
        prefix = f'{const.REFERENCE_COMPANY_PREFIX}{self.company_id.id}-' if self._neoship_multi_company() else ''
        deliveries = self.sale_id.picking_ids.filtered(
            lambda picking: picking.picking_type_code == const.ODOO_PICKING_TYPE_OUTGOING
        ).sorted('id')
        if self not in deliveries:
            return neoship_reference(prefix, self.name, 1)
        delivery = deliveries.ids.index(self.id) + 1
        if delivery > const.REFERENCE_MAX_DELIVERIES:
            raise UserError(
                self.env._(
                    'Transfer %(transfer)s is delivery %(delivery)s of order %(order)s, but Neoship references '
                    'number at most %(limit)s deliveries of an order.',
                    transfer=self.name,
                    delivery=delivery,
                    order=self.sale_id.name,
                    limit=const.REFERENCE_MAX_DELIVERIES,
                )
            )
        return neoship_reference(prefix, self.sale_id.name, delivery)

    def _neoship_check_references_free(self, packages):
        self.ensure_one()
        references = []
        for package in packages:
            reference = package['reference_number']
            references.append(reference)
            # Neoship appends a numeric suffix to copies created through count_of_packages.
            references.extend(f'{reference}{sequence}' for sequence in range(1, package.get('count_of_packages', 1)))
        other = (
            self.env['neoship.parcel']
            .sudo()
            .search([('reference', 'in', references), ('picking_id', '!=', self.id)], limit=1)
        )
        if other:
            raise UserError(
                self.env._(
                    'Neoship reference %(reference)s of transfer %(transfer)s is already used by transfer '
                    '%(other)s (%(company)s).',
                    reference=other.reference,
                    transfer=self.name,
                    other=other.picking_id.name,
                    company=other.company_id.name,
                )
            )

    def _neoship_prepare_packages(self):
        self.ensure_one()
        package = self._neoship_prepare_package()
        packs = self._neoship_packs()
        if packs and self.move_line_ids.filtered(lambda line: not line.result_package_id):
            raise UserError(
                self.env._(
                    'Put all products of transfer %s in packs, or none of them: Neoship sends one parcel per pack.',
                    self.name,
                )
            )
        if self._neoship_ships_pack_per_shipment(packs):
            packages = []
            for sequence, pack in enumerate(packs, start=1):
                parcel = dict(package)
                if sequence > 1:
                    for field in const.COD_FIELDS:
                        parcel.pop(field, None)
                parcel['reference_number'] = neoship_parcel_reference(package['reference_number'], sequence)
                weight = self._neoship_weight_kg(pack.shipping_weight or pack.weight)
                self._neoship_set_weight(parcel, weight)
                self._neoship_set_size_category(parcel, pack)
                packages.append(parcel)
            return packages
        count = len(packs) or 1
        if count == 1:
            self._neoship_set_size_category(package, packs)
        package['count_of_packages'] = count
        # Neoship copies the main package's weight to every extra parcel.
        self._neoship_set_weight(
            package, float_round(self._neoship_weight_kg() / count, precision_digits=const.WEIGHT_PRECISION_DIGITS)
        )
        return [package]

    def _neoship_packs(self):
        return self.move_line_ids.result_package_id.outermost_package_id.sorted('id').with_context(picking_id=self.id)

    def _neoship_ships_pack_per_shipment(self, packs):
        # Neoship creates extra parcels from count_of_packages only for home delivery and not for Packeta.
        return len(packs) > 1 and (
            self.carrier_id._neoship_ignores_package_count() or bool(self.sale_id.neoship_parcelshop_id)
        )

    def _neoship_set_weight(self, package, weight):
        # Neoship validates the weight against the carrier's limits.
        if weight > 0:
            package['weight'] = weight

    def _neoship_set_size_category(self, package, pack):
        if not self.carrier_id.neoship_has_carrier_type:
            return
        domain = self._neoship_package_type_domain()
        package_type = pack.package_type_id
        if not package_type._neoship_size_category():
            package_type = self.carrier_id.neoship_package_type_id.filtered_domain(domain)
        elif not package_type.filtered_domain(domain):
            raise UserError(
                self.env._(
                    'Pack %(pack)s of transfer %(transfer)s has package type %(type)s, '
                    'a size of another Packeta carrier than the one the transfer is sent with.',
                    pack=pack.name,
                    transfer=self.name,
                    type=package_type.name,
                )
            )
        size_category = package_type._neoship_size_category()
        if size_category:
            package['others'] = {'size_category': size_category}

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
        }
        self._neoship_check_addresses(package, sender, receiver)

        parcelshop = self.sale_id.neoship_parcelshop_id
        if parcelshop:
            package['parcelshop'] = parcelshop
        elif carrier.neoship_has_carrier_type:
            self._neoship_check_packeta_country(receiver)
        carrier_type = self._neoship_packeta_carrier_type()
        if carrier_type:
            package['carrier_type'] = carrier_type

        package.update(self._neoship_cod_values())
        return package

    def _neoship_packeta_carrier_type(self):
        if not self.carrier_id.neoship_has_carrier_type:
            return 0
        if self.sale_id.neoship_parcelshop_id:
            return self.sale_id.neoship_parcelshop_carrier_type
        return self.carrier_id.neoship_carrier_type

    def _neoship_package_type_domain(self):
        domain = [('package_carrier_type', '=', const.DELIVERY_TYPE)]
        if not self.carrier_id.neoship_has_carrier_type:
            return [*domain, ('neoship_carrier_type', '=', 0)]
        carrier_type = self._neoship_packeta_carrier_type()
        # Without a carrier the pickup point decides it, so a size of any Packeta carrier may fit.
        if not carrier_type:
            return domain
        return [*domain, ('neoship_carrier_type', 'in', (0, carrier_type))]

    def _neoship_address_values(self, prefix, partner, contacts):
        commercial = partner.commercial_partner_id
        phone_contact = contacts.filtered('phone')[:1]
        return {
            f'{prefix}_name': partner.name or commercial.name,
            f'{prefix}_company': commercial.name if commercial.is_company and commercial != partner else '',
            f'{prefix}_street': ', '.join(filter(None, [partner.street, partner.street2])),
            f'{prefix}_city': partner.city,
            f'{prefix}_zip': partner.zip,
            f'{prefix}_state_code': partner.country_id.code,
            f'{prefix}_email': next(iter(contacts.filtered('email').mapped('email')), False),
            f'{prefix}_phone': neoship_phone(phone_contact.phone, phone_contact.country_id or partner.country_id),
        }

    def _neoship_check_addresses(self, package, sender, receiver):
        labels = self.carrier_id._neoship_address_labels()
        del labels['company']

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

    def _neoship_weight_kg(self, weight=None):
        if weight is None:
            weight = self.shipping_weight or self.weight
        weight = weight or self.carrier_id.neoship_default_weight
        weight_uom = self.env['product.template']._get_weight_uom_id_from_ir_config_parameter()
        weight_kg = weight_uom._compute_quantity(weight, self.env.ref(const.ODOO_UOM_KG), round=False)
        return float_round(weight_kg, precision_digits=const.WEIGHT_PRECISION_DIGITS)

    def _neoship_cod_values(self):
        order = self.sale_id
        if self.neoship_cod_manual:
            amount = self.neoship_cod_manual_amount
        elif self.carrier_id._neoship_is_cod(order):
            (order.picking_ids - self).filtered(
                lambda picking: (
                    picking.picking_type_code == const.ODOO_PICKING_TYPE_OUTGOING
                    and picking.state != const.ODOO_PICKING_STATE_CANCEL
                )
            )._neoship_lock_for_order(order)
            amount = self._neoship_cod_amount()
        else:
            return {}
        currency = self._neoship_cod_currency()
        if currency.compare_amounts(amount, 0) < 0:
            raise UserError(
                self.env._(
                    'The cash on delivery amount of transfer %(transfer)s would be %(amount)s, '
                    'for example because of a discount on order %(order)s. '
                    'Set the cash on delivery amount manually.',
                    transfer=self.name,
                    amount=format_amount(self.env, amount, currency),
                    order=order.name,
                )
            )
        if currency.is_zero(amount):
            return {}
        return {
            'cod_price': currency.round(amount),
            'cod_currency_code': currency.name,
            'cod_reference': self._neoship_cod_reference(),
        }

    def _neoship_cod_reference(self):
        source = self.sale_id or self
        if not self.carrier_id._neoship_numeric_cod_reference():
            return neoship_code(source.name)
        digits = neoship_digits(source.name) or str(source.id)
        return digits[-const.NUMERIC_COD_REFERENCE_MAX_LENGTH :]

    def _neoship_cod_currency(self):
        return self.sale_id.currency_id or self.company_id.currency_id

    def _neoship_convert_cod(self, packages, currency, target_code):
        self.ensure_one()
        target = self.env['res.currency'].with_context(active_test=False).search([('name', '=', target_code)], limit=1)
        company = self.company_id
        country = self.partner_id.country_id.name
        # Odoo converts at rate 1 when a currency has no rate, which is the mistake this conversion prevents.
        if not target or not all(self._neoship_has_rate(item, company) for item in currency | target):
            raise UserError(
                self.env._(
                    'Neoship collects cash on delivery in %(country)s only in %(target)s. '
                    'Activate %(target)s and %(currency)s with exchange rates, so the cash on delivery of '
                    'transfer %(transfer)s can be converted.',
                    country=country,
                    target=target_code,
                    currency=currency.name,
                    transfer=self.name,
                )
            )
        date = fields.Date.context_today(self)
        amounts = []
        for package in packages:
            amount = package['cod_price']
            package['cod_price'] = currency._convert(amount, target, company, date)
            package['cod_currency_code'] = target.name
            amounts.append((amount, package['cod_price']))
        self.message_post(
            body=self.env._(
                'Neoship collects cash on delivery in %(country)s only in %(target)s, so %(amounts)s was converted '
                'at the rate of %(date)s.',
                country=country,
                target=target.name,
                amounts=', '.join(
                    self.env._(
                        '%(amount)s to %(converted)s',
                        amount=format_amount(self.env, amount, currency),
                        converted=format_amount(self.env, converted, target),
                    )
                    for amount, converted in amounts
                ),
                date=format_date(self.env, date),
            )
        )
        return target

    def _neoship_has_rate(self, currency, company):
        root = company.root_id
        return currency == root.currency_id or bool(
            self.env['res.currency.rate']
            .sudo()
            .search_count([('currency_id', '=', currency.id), ('company_id', 'in', (False, root.id))], limit=1)
        )

    def _neoship_cod_amount(self):
        # The first delivery also collects the services, the one completing the order the rest of its total;
        # a negative share is deducted from the next delivery.
        self.ensure_one()
        order = self.sale_id
        currency = self._neoship_cod_currency()
        lines = order.order_line.filtered(lambda line: not line.display_type and not line.is_downpayment)
        goods = lines.filtered(
            lambda line: (
                line.product_type == const.ODOO_PRODUCT_TYPE_GOODS
                and not line.product_uom_id.is_zero(line.product_uom_qty)
            )
        )
        services = lines.filtered(lambda line: line.product_type == const.ODOO_PRODUCT_TYPE_SERVICE)
        moves = self.env['stock.move']
        delivered = dict.fromkeys(goods, 0.0)
        collected = carried = 0.0
        for index, picking in enumerate(self._neoship_cod_deliveries()):
            moves |= picking.move_ids.filtered(
                lambda move: move.state != const.ODOO_MOVE_STATE_CANCEL and move.sale_line_id in goods
            )
            amount = carried + (sum(services.mapped('price_total')) if index == 0 else 0.0)
            for line in goods:
                line_moves = moves.filtered(lambda move, line=line: move.sale_line_id == line)
                quantity = line_moves._neoship_delivered_quantity(line)
                amount += (quantity - delivered[line]) * line.price_total / line.product_uom_qty
                delivered[line] = quantity
            completes = all(line.product_uom_id.compare(delivered[line], line.product_uom_qty) >= 0 for line in goods)
            amount = currency.round(order.amount_total - collected if completes else amount)
            carried = 0.0
            if not completes and currency.compare_amounts(amount, 0) < 0:
                carried, amount = amount, 0.0
            if picking == self:
                return amount
            collected += amount
        return collected

    def _neoship_cod_deliveries(self):
        done = self.sale_id.picking_ids.filtered(
            lambda picking: (
                picking.picking_type_code == const.ODOO_PICKING_TYPE_OUTGOING
                and picking.state == const.ODOO_PICKING_STATE_DONE
            )
        )
        return (done | self).sorted(
            lambda picking: (not picking.date_done, picking.date_done or datetime.min, picking.id)
        )

    def _neoship_attach_label(self, client, tracking_number):
        self.ensure_one()
        main = self._neoship_main_parcel()
        label = client.get_label(main.neoship_id)
        name = f'{self.carrier_id._get_delivery_label_prefix()}-{(tracking_number or "").replace(",", "-")}.pdf'
        message = self.message_post(body=self.env._('Neoship shipping label'), attachments=[(name, label)])
        main.label_id = message.attachment_ids[:1]

    def _neoship_main_parcel(self):
        self.ensure_one()
        return self.neoship_parcel_ids[:1]

    def _neoship_store_parcels(self, packages, parcels, prod_environment, currency):
        self.ensure_one()
        packs = self._neoship_packs()
        if len(packs) != len(parcels):
            packs = self.env['stock.package']
        self.neoship_parcel_ids.unlink()
        values = []
        for index, parcel in enumerate(parcels):
            # Neoship creates the copies from count_of_packages; they belong to the main parcel.
            is_copy = index >= len(packages)
            package = {} if is_copy else packages[index]
            values.append(
                {
                    'picking_id': self.id,
                    'package_id': packs[index].id if packs else False,
                    'sequence': index,
                    'neoship_id': parcel.id,
                    'reference': package.get('reference_number') or parcel.reference_number,
                    'tracking_ref': parcel.tracking_number,
                    'is_copy': is_copy,
                    'cod_amount': package.get('cod_price', 0.0),
                    'cod_currency_id': currency.id,
                    'prod_environment': prod_environment,
                }
            )
        self.env['neoship.parcel'].create(values)
        self.neoship_reference = packages[0]['reference_number']

    def _neoship_post_status_change(self, groups_before):
        for picking in self:
            group = picking.neoship_status_group
            if group and group != groups_before.get(picking):
                picking.message_post(
                    body=self.env._(
                        'Neoship shipment %(tracking)s: %(status)s',
                        tracking=picking.carrier_tracking_ref,
                        status=picking.neoship_status,
                    ),
                    subtype_xmlid='mail.mt_note',
                )

    def action_neoship_open_label(self):
        self.ensure_one()
        main = self._neoship_main_parcel()
        if not main.label_id:
            self.action_neoship_download_label()
        return {'type': 'ir.actions.act_url', 'url': f'/web/content/{main.label_id.id}', 'target': 'new'}

    def action_neoship_download_label(self):
        self.ensure_one()
        main = self._neoship_main_parcel()
        self.carrier_id._neoship_fetch(
            lambda client: self._neoship_attach_label(client, self.carrier_tracking_ref),
            main.prod_environment,
        )
        main.error = False

    def action_neoship_update_tracking(self):
        self.neoship_parcel_ids._update_tracking()

    def cancel_shipment(self):
        neoship = self.filtered(lambda picking: picking.delivery_type == const.DELIVERY_TYPE)
        super(StockPicking, self - neoship).cancel_shipment()
        # Core always reports success and clears the tracking number; a refused cancel must keep both.
        refused = self.browse()
        for picking in neoship:
            picking_refused = picking.carrier_id.cancel_shipment(picking)
            if picking_refused:
                refused |= picking_refused
                continue
            picking.message_post(body=self.env._('Shipment %s cancelled', picking.carrier_tracking_ref))
            picking.carrier_tracking_ref = False
        if not refused:
            return None
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'warning',
                'title': self.env._('Neoship'),
                'message': '\n'.join(refused.neoship_parcel_ids.filtered('cancel_refused').mapped('error')),
                'sticky': True,
            },
        }
