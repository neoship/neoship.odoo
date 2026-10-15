from odoo import fields, models

from .. import const


class NeoshipOptionWizard(models.TransientModel):
    _name = 'neoship.option.wizard'
    _description = 'Choose Neoship Option'

    carrier_id = fields.Many2one('delivery.carrier', required=True, ondelete='cascade')
    kind = fields.Selection(
        [
            (const.OPTION_KIND_SHIPPER, 'Neoship Carrier'),
            (const.OPTION_KIND_CARRIER_TYPE, 'Packeta Home Delivery Carrier'),
            (const.OPTION_KIND_LABEL_FORMAT, 'Label Format'),
        ],
        required=True,
    )
    line_ids = fields.One2many('neoship.option.wizard.line', 'wizard_id')
    shipper_id = fields.Integer(string='Neoship Carrier ID')
    shipper_code = fields.Char(string='Neoship Carrier Code')
    shipper_name = fields.Char(string='Neoship Carrier')
    print_formats = fields.Json()
    has_pickup_point_only = fields.Boolean(compute='_compute_has_pickup_point_only')

    def _compute_has_pickup_point_only(self):
        for wizard in self:
            wizard.has_pickup_point_only = any(line.pickup_point_only for line in wizard.line_ids)


class NeoshipOptionWizardLine(models.TransientModel):
    _name = 'neoship.option.wizard.line'
    _description = 'Neoship Option'
    _order = 'sequence, name'

    wizard_id = fields.Many2one('neoship.option.wizard', required=True, ondelete='cascade')
    sequence = fields.Integer()
    value = fields.Integer(required=True)
    name = fields.Char(required=True)
    code = fields.Char()
    country_id = fields.Many2one('res.country')
    currency = fields.Char()
    supports_parcelshops = fields.Boolean(string='Pickup Points')
    pickup_point_only = fields.Boolean(string='Pickup Points Only')
    print_formats = fields.Json()

    def action_select(self):
        self.ensure_one()
        wizard = self.wizard_id
        carrier = wizard.carrier_id
        schedules = self.env['neoship.closure.schedule']
        if wizard.kind == const.OPTION_KIND_SHIPPER:
            if carrier._neoship_requires_carrier_type(self.code):
                return carrier._neoship_open_carrier_type_wizard(self.value, self.code, self.name, self.print_formats)
            schedules = carrier._neoship_set_shipper(self.value, self.code, self.name, print_formats=self.print_formats)
        elif wizard.kind == const.OPTION_KIND_LABEL_FORMAT:
            carrier.write(carrier._neoship_label_format_values(wizard.print_formats, self.code))
        elif wizard.shipper_id:
            schedules = carrier._neoship_set_shipper(
                wizard.shipper_id,
                wizard.shipper_code,
                wizard.shipper_name,
                self.value,
                self.name,
                self.country_id.id,
                print_formats=wizard.print_formats,
            )
        else:
            carrier._neoship_set_carrier_type(self.value, self.name, self.country_id.id)
        return carrier._neoship_closure_schedule_notification(schedules)
