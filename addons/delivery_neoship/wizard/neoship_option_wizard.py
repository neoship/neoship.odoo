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
        ],
        required=True,
    )
    line_ids = fields.One2many('neoship.option.wizard.line', 'wizard_id')
    shipper_id = fields.Integer(string='Neoship Carrier ID')
    shipper_code = fields.Char(string='Neoship Carrier Code')
    shipper_name = fields.Char(string='Neoship Carrier')


class NeoshipOptionWizardLine(models.TransientModel):
    _name = 'neoship.option.wizard.line'
    _description = 'Neoship Option'
    _order = 'name'

    wizard_id = fields.Many2one('neoship.option.wizard', required=True, ondelete='cascade')
    value = fields.Integer(required=True)
    name = fields.Char(required=True)
    code = fields.Char()
    country_id = fields.Many2one('res.country')
    currency = fields.Char()
    supports_parcelshops = fields.Boolean(string='Pickup Points')

    def action_select(self):
        self.ensure_one()
        wizard = self.wizard_id
        carrier = wizard.carrier_id
        schedules = self.env['neoship.closure.schedule']
        if wizard.kind == const.OPTION_KIND_SHIPPER:
            if carrier._neoship_requires_carrier_type(self.code):
                return carrier._neoship_open_carrier_type_wizard(self.value, self.code, self.name)
            schedules = carrier._neoship_set_shipper(self.value, self.code, self.name)
        elif wizard.shipper_id:
            schedules = carrier._neoship_set_shipper(
                wizard.shipper_id, wizard.shipper_code, wizard.shipper_name, self.value, self.name, self.country_id.id
            )
        else:
            carrier._neoship_set_carrier_type(self.value, self.name, self.country_id.id)
        return carrier._neoship_closure_schedule_notification(schedules)
