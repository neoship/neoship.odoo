import base64
import binascii

from odoo import api, fields, models

from .. import const


class NeoshipClosure(models.Model):
    _name = 'neoship.closure'
    _description = 'Neoship Closure'
    _order = 'closed_at desc, id desc'

    name = fields.Char(compute='_compute_name')
    schedule_id = fields.Many2one(
        'neoship.closure.schedule', readonly=True, ondelete='set null', index='btree_not_null'
    )
    carrier_id = fields.Many2one('delivery.carrier', string='Delivery Method', required=True, readonly=True)
    shipper_name = fields.Char(string='Neoship Carrier', readonly=True)
    prod_environment = fields.Boolean(string='Production', readonly=True)
    action = fields.Char(string='Neoship Action', readonly=True)
    closed_at = fields.Datetime(required=True, readonly=True, default=fields.Datetime.now)
    closure_date = fields.Date(required=True, readonly=True, index=True)
    date_from = fields.Date(
        string='Shipments From',
        readonly=True,
        help='Packeta closes the shipments created since this date that it has not picked up yet.',
    )
    state = fields.Selection(
        [
            (const.CLOSURE_STATE_DONE, 'Closed'),
            (const.CLOSURE_STATE_EMPTY, 'Nothing to Close'),
            (const.CLOSURE_STATE_FAILED, 'Failed'),
        ],
        string='Result',
        required=True,
        readonly=True,
    )
    message = fields.Text(readonly=True)
    protocol = fields.Binary(readonly=True, attachment=True)
    protocol_filename = fields.Char(readonly=True)

    @api.depends('shipper_name', 'closure_date')
    def _compute_name(self):
        for closure in self:
            closure.name = f'{closure.shipper_name or closure.carrier_id.name} {closure.closure_date or ""}'.strip()

    @api.model
    def _neoship_result_values(self, result, shipper_code, closure_date):
        if not isinstance(result, dict):
            return {
                'state': const.CLOSURE_STATE_FAILED,
                'message': self.env._('Neoship returned an unexpected closure response.'),
            }
        errors = result.get('errors') or ''
        errors = '; '.join(str(error) for error in errors) if isinstance(errors, list) else str(errors)
        package_ids = result.get('package_ids') or []
        values = {'message': errors or False}
        protocol = result.get('protocol') or ''
        if protocol:
            try:
                pdf = base64.b64decode(protocol)
            except (binascii.Error, ValueError):
                return {
                    **values,
                    'state': const.CLOSURE_STATE_FAILED,
                    'message': self.env._('Neoship returned a protocol that is not a valid file.'),
                }
            values.update(
                {
                    'protocol': base64.b64encode(pdf),
                    'protocol_filename': f'{shipper_code}-protocol-{closure_date}.pdf',
                }
            )
        if protocol or package_ids:
            return {**values, 'state': const.CLOSURE_STATE_DONE}
        if errors.strip() == const.CLOSURE_NO_PACKAGES:
            return {**values, 'state': const.CLOSURE_STATE_EMPTY, 'message': False}
        return {
            **values,
            'state': const.CLOSURE_STATE_FAILED,
            'message': errors or self.env._('Neoship closed nothing and returned no protocol.'),
        }
