import logging
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import quote

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import split_every

from .. import const
from ..tools import neoship_status_group
from .neoship_api import (
    PROD_TRACKING_URL,
    TEST_TRACKING_URL,
    NeoshipConnectionError,
    NeoshipError,
    NeoshipNotFoundError,
)

_logger = logging.getLogger(__name__)


@dataclass
class NeoshipTrackingRun:
    on_batch: object = None
    checked: int = 0
    changed: int = 0
    failed: int = 0
    unreachable: bool = False
    out_of_time: bool = False

    @property
    def stopped(self):
        return self.unreachable or self.out_of_time

    def done(self, parcels, changed=0, failed=0):
        self.checked += len(parcels)
        self.changed += changed
        self.failed += failed
        # ir.cron._commit_progress returns the time left for the job.
        if self.on_batch and not self.on_batch(len(parcels)):
            self.out_of_time = True


class NeoshipParcel(models.Model):
    _name = 'neoship.parcel'
    _description = 'Neoship Parcel'
    _order = 'picking_id, sequence, id'
    _rec_name = 'reference'

    picking_id = fields.Many2one('stock.picking', required=True, index=True, ondelete='cascade', readonly=True)
    company_id = fields.Many2one(related='picking_id.company_id', store=True, index=True)
    package_id = fields.Many2one('stock.package', index='btree_not_null', ondelete='set null', readonly=True)
    sequence = fields.Integer(readonly=True)
    neoship_id = fields.Integer(string='Neoship ID', required=True, readonly=True)
    reference = fields.Char(required=True, readonly=True)
    tracking_ref = fields.Char(string='Tracking Number', readonly=True)
    is_copy = fields.Boolean(
        readonly=True,
        help='Neoship created this parcel from the package count of the main parcel and cancels it with the main one.',
    )
    prod_environment = fields.Boolean(string='Production', readonly=True)
    cod_amount = fields.Monetary(string='Cash on Delivery', currency_field='cod_currency_id', readonly=True)
    cod_currency_id = fields.Many2one('res.currency', string='Cash on Delivery Currency', readonly=True)
    label_id = fields.Many2one('ir.attachment', readonly=True)
    status = fields.Char(readonly=True)
    status_id = fields.Integer(string='Status ID', readonly=True)
    status_group = fields.Selection(const.STATUS_GROUP_SELECTION, string='Delivery', readonly=True, index=True)
    status_date = fields.Datetime(string='Status Changed', readonly=True)
    last_sync = fields.Datetime(readonly=True)
    sync_error = fields.Text(string='Tracking Error', readonly=True)
    error = fields.Text(readonly=True)
    cancel_refused = fields.Boolean(
        readonly=True,
        help='Neoship refused to cancel the parcel because the carrier already has it.',
    )

    _reference_uniq = models.Constraint(
        'UNIQUE(reference)',
        'This Neoship reference is already used by another parcel.',
    )

    def _tracking_url(self):
        self.ensure_one()
        base_url = PROD_TRACKING_URL if self.prod_environment else TEST_TRACKING_URL
        return f'{base_url}{quote(self.tracking_ref)}/'

    def action_open_label(self):
        self.ensure_one()
        return self.picking_id.action_neoship_open_label()

    def action_open_tracking(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url', 'url': self._tracking_url(), 'target': 'new'}

    @api.model
    def _cron_update_tracking(self):
        days = int(
            self.env['ir.config_parameter'].sudo().get_param(const.TRACKING_DAYS_PARAM, const.TRACKING_DAYS_DEFAULT)
        )
        now = fields.Datetime.now()
        # Odoo reruns the job while progress reports remaining work; skipping fresh syncs lets the cycle end.
        parcels = self.search(
            [
                *self._tracking_domain(now - timedelta(days=days)),
                '|',
                ('last_sync', '=', False),
                ('last_sync', '<', now - timedelta(minutes=const.TRACKING_RECHECK_MINUTES)),
            ],
            order='last_sync ASC NULLS FIRST, id',
            limit=const.TRACKING_LIMIT_PER_RUN,
        )
        cron = self.env['ir.cron'] if self.env.context.get('cron_id') else None
        if cron is not None:
            cron._commit_progress(remaining=len(parcels))
        run = parcels._update_tracking(cron._commit_progress if cron is not None else None)
        if cron is not None and run.unreachable:
            cron._commit_progress(remaining=0)
        _logger.info('Neoship tracking: %s checked, %s changed, %s failed', run.checked, run.changed, run.failed)

    @api.model
    def _tracking_domain(self, cutoff):
        return [
            ('picking_id.carrier_id.delivery_type', '=', const.DELIVERY_TYPE),
            ('tracking_ref', '!=', False),
            '|',
            ('status_group', '=', False),
            ('status_group', 'not in', const.STATUS_GROUPS_FINAL),
            '|',
            ('status_date', '>=', cutoff),
            '&',
            ('status_date', '=', False),
            ('picking_id.date_done', '>=', cutoff),
        ]

    def _update_tracking(self, on_batch=None):
        run = NeoshipTrackingRun(on_batch)
        for (carrier, prod_environment), parcels in self.grouped(
            lambda parcel: (parcel.picking_id.carrier_id, parcel.prod_environment)
        ).items():
            if run.stopped:
                break
            parcels._update_account_tracking(carrier, prod_environment, run)
        return run

    def _update_account_tracking(self, carrier, prod_environment, run):
        environment = const.ENVIRONMENT_PRODUCTION if prod_environment else const.ENVIRONMENT_TEST
        synced = self.browse()
        try:
            with carrier._neoship_client(prod_environment) as client:
                client.login()
                for batch in split_every(const.TRACKING_BATCH_SIZE, self.ids, self.browse):
                    changed, failed = batch._sync_batch(client, carrier, environment)
                    synced |= batch
                    run.done(batch, changed, failed)
                    if run.stopped:
                        break
        except (NeoshipError, UserError) as e:
            _logger.warning('Neoship tracking failed for delivery method %s (%s): %s', carrier.name, environment, e)
            run.unreachable = isinstance(e, NeoshipConnectionError)
            rest = self - synced
            rest._sync_failed(carrier._neoship_error_message(e) if isinstance(e, NeoshipError) else str(e))
            run.done(rest, failed=len(rest))

    def _sync_created(self, client, carrier):
        environment = const.ENVIRONMENT_PRODUCTION if carrier.prod_environment else const.ENVIRONMENT_TEST
        try:
            self._sync_batch(client, carrier, environment, notify=False)
        except NeoshipConnectionError as e:
            _logger.warning('Neoship tracking failed for delivery method %s (%s): %s', carrier.name, environment, e)
            self._sync_failed(carrier._neoship_error_message(e))

    def _sync_batch(self, client, carrier, environment, notify=True):
        try:
            by_id = {shipment.id: shipment for shipment in client.find_packages(self.mapped('reference'))}
        except NeoshipConnectionError:
            raise
        except NeoshipError as e:
            _logger.warning(
                'Neoship tracking failed for %s parcels of delivery method %s (%s): %s',
                len(self),
                carrier.name,
                environment,
                e,
            )
            self._sync_failed(carrier._neoship_error_message(e))
            return 0, len(self)
        pickings = self.picking_id
        groups_before = {picking: picking.neoship_status_group for picking in pickings}
        changed = failed = 0
        for parcel in self:
            shipment = by_id.get(parcel.neoship_id) or parcel._read_shipment(client)
            if shipment:
                changed += parcel._apply_status(shipment)
            else:
                failed += 1
        if notify:
            pickings._neoship_post_status_change(groups_before)
        return changed, failed

    def _read_shipment(self, client):
        self.ensure_one()
        try:
            return client.get_package(self.neoship_id)
        except NeoshipConnectionError:
            raise
        except NeoshipNotFoundError:
            _logger.warning(
                'Neoship shipment %s (package %s, transfer %s) was not found',
                self.tracking_ref,
                self.neoship_id,
                self.picking_id.name,
            )
            message = self.env._('Neoship shipment %s was not found.', self.tracking_ref)
        except NeoshipError as e:
            _logger.warning(
                'Neoship tracking failed for shipment %s (transfer %s): %s',
                self.tracking_ref,
                self.picking_id.name,
                e,
            )
            message = self.picking_id.carrier_id._neoship_error_message(e)
        self._sync_failed(message)
        return None

    def _apply_status(self, shipment):
        self.ensure_one()
        status = shipment.last_status
        status_id = status.id if status else 0
        name = (status and status.name) or False
        now = fields.Datetime.now()
        vals = {
            'status': name,
            'status_group': neoship_status_group(status),
            'last_sync': now,
            'sync_error': False,
        }
        changed = status_id != self.status_id or name != self.status
        if changed:
            vals.update({'status_id': status_id, 'status_date': now})
        self.write(vals)
        return changed

    def _sync_failed(self, message):
        self.write({'sync_error': message, 'last_sync': fields.Datetime.now()})
