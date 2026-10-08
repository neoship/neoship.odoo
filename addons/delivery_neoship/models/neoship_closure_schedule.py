import logging
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.base.models.res_partner import _tz_get

from .. import const
from .neoship_api import NeoshipError

_logger = logging.getLogger(__name__)

NEXT_RUN_DEPENDS = {'active', 'closure_time', 'tz'}


class NeoshipClosureSchedule(models.Model):
    _name = 'neoship.closure.schedule'
    _description = 'Neoship Closure Schedule'
    _order = 'closure_time, id'

    name = fields.Char(related='carrier_id.name', string='Name')
    active = fields.Boolean(default=True)
    carrier_id = fields.Many2one(
        'delivery.carrier',
        string='Delivery Method',
        required=True,
        ondelete='restrict',
        domain=[('neoship_has_closure', '=', True)],
        help='The delivery method sets the Neoship account and carrier. Only carriers with a closure are offered.',
    )
    shipper_name = fields.Char(related='carrier_id.neoship_shipper_name', string='Neoship Carrier')
    closure_time = fields.Float(string='Time', required=True, default=const.CLOSURE_DEFAULT_TIME)
    tz = fields.Selection(_tz_get, string='Timezone', required=True, default=lambda self: self.env.user.tz or 'UTC')
    mon = fields.Boolean(default=True)
    tue = fields.Boolean(default=True)
    wed = fields.Boolean(default=True)
    thu = fields.Boolean(default=True)
    fri = fields.Boolean(default=True)
    sat = fields.Boolean()
    sun = fields.Boolean()
    next_run = fields.Datetime(copy=False, readonly=True, index=True)
    closure_ids = fields.One2many('neoship.closure', 'schedule_id', string='Closures')
    closure_count = fields.Integer(compute='_compute_closure_count')

    _closure_time_range = models.Constraint(
        'CHECK(closure_time >= 0 AND closure_time < 24)',
        'The closure time must be between 00:00 and 23:59.',
    )

    @api.depends('closure_ids')
    def _compute_closure_count(self):
        counts = dict(
            self.env['neoship.closure']._read_group([('schedule_id', 'in', self.ids)], ['schedule_id'], ['__count'])
        )
        for schedule in self:
            schedule.closure_count = counts.get(schedule, 0)

    @api.constrains('carrier_id')
    def _check_carrier_id(self):
        for schedule in self:
            if not schedule.carrier_id._neoship_closure_action():
                raise ValidationError(
                    self.env._(
                        'Delivery method %s has no Neoship carrier with a closure. '
                        'Closures are available for SPS, Packeta and Slovenská pošta.',
                        schedule.carrier_id.name,
                    )
                )

    @api.model_create_multi
    def create(self, vals_list):
        schedules = super().create(vals_list)
        schedules._schedule_next_run()
        return schedules

    def write(self, vals):
        result = super().write(vals)
        if not NEXT_RUN_DEPENDS.isdisjoint(vals):
            self._schedule_next_run()
        return result

    def _schedule_next_run(self):
        for schedule in self:
            schedule.next_run = schedule.active and schedule._next_call()
        next_runs = [run for run in self.mapped('next_run') if run]
        cron = self.env.ref(const.CLOSURE_CRON_XMLID, raise_if_not_found=False)
        if cron and next_runs:
            cron._trigger(next_runs)

    @api.model
    def _cron_run_closures(self):
        schedules = self.search([('next_run', '<=', fields.Datetime.now())])
        cron = self.env['ir.cron'] if self.env.context.get('cron_id') else None
        if cron:
            cron._commit_progress(remaining=len(schedules))
        for schedule in schedules:
            schedule._run_scheduled()
            schedule._schedule_next_run()
            if cron:
                cron._commit_progress(1)

    def _next_call(self):
        self.ensure_one()
        tz = pytz.timezone(self.tz)
        now = pytz.utc.localize(fields.Datetime.now()).astimezone(tz).replace(tzinfo=None)
        hours, minutes = divmod(round(self.closure_time * 60), 60)
        run_at = datetime.combine(now.date(), time(hours, minutes))
        if run_at <= now:
            run_at += timedelta(days=1)
        return tz.localize(run_at).astimezone(pytz.utc).replace(tzinfo=None)

    def _today(self):
        self.ensure_one()
        return fields.Date.context_today(self.with_context(tz=self.tz))

    def _run_scheduled(self):
        self.ensure_one()
        today = self._today()
        if not self[const.WEEKDAY_FIELDS[today.weekday()]]:
            return
        if self._closed_recently():
            _logger.info('Neoship closure for delivery method %s skipped: the account was just closed', self.name)
            return
        self._close(today)

    def action_close_now(self):
        self.ensure_one()
        closure = self._close(self._today())
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'neoship.closure',
            'res_id': closure.id,
            'view_mode': 'form',
        }

    def action_view_closures(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('delivery_neoship.action_neoship_closure')
        action['domain'] = [('schedule_id', '=', self.id)]
        return action

    def _closes_by_date(self):
        return (self.carrier_id.neoship_shipper_code or '').lower() in const.CLOSURE_SHIPPERS_BY_DATE

    def _account_closures_domain(self):
        carrier = self.carrier_id.sudo()
        same_account = carrier.with_context(active_test=False).search(
            [
                ('delivery_type', '=', const.DELIVERY_TYPE),
                ('neoship_username', '=', carrier.neoship_username),
            ]
        )
        return [
            ('carrier_id', 'in', same_account.ids),
            ('action', '=', carrier._neoship_closure_action()),
            ('prod_environment', '=', carrier.prod_environment),
            ('state', '=', const.CLOSURE_STATE_DONE),
        ]

    def _closed_recently(self):
        since = fields.Datetime.now() - timedelta(minutes=const.CLOSURE_DEDUP_MINUTES)
        return bool(
            self.env['neoship.closure'].search_count(
                [*self._account_closures_domain(), ('closed_at', '>=', since)], limit=1
            )
        )

    def _date_from(self, today):
        last = self.env['neoship.closure'].search(self._account_closures_domain(), order='closure_date desc', limit=1)
        if not last:
            return today
        return max(last.closure_date, today - timedelta(days=const.CLOSURE_MAX_DAYS))

    def _close(self, closure_date):
        self.ensure_one()
        carrier = self.carrier_id
        action = carrier._neoship_closure_action()
        values = {
            'schedule_id': self.id,
            'carrier_id': carrier.id,
            'shipper_name': carrier.neoship_shipper_name,
            'prod_environment': carrier.prod_environment,
            'action': action,
            'closure_date': closure_date,
        }
        if action:
            if self._closes_by_date():
                values['date_from'] = self._date_from(closure_date)
            values.update(self._call_neoship(carrier, action, values.get('date_from'), closure_date))
        else:
            values.update(
                {
                    'state': const.CLOSURE_STATE_FAILED,
                    'message': self.env._('Delivery method %s has no Neoship carrier with a closure.', carrier.name),
                }
            )
        closure = self.env['neoship.closure'].create(values)
        _logger.info('Neoship closure for delivery method %s: %s', carrier.name, closure.state)
        return closure

    def _call_neoship(self, carrier, action, date_from, closure_date):
        try:
            with carrier._neoship_client(timeout=const.CLOSURE_TIMEOUT) as client:
                result = client.close_day(action, date_from)
        except NeoshipError as e:
            _logger.warning('Neoship closure failed for delivery method %s: %s', carrier.name, e)
            return {'state': const.CLOSURE_STATE_FAILED, 'message': carrier._neoship_user_error(e).args[0]}
        except UserError as e:
            return {'state': const.CLOSURE_STATE_FAILED, 'message': e.args[0]}
        return self.env['neoship.closure']._neoship_result_values(result, carrier.neoship_shipper_code, closure_date)
