from odoo import api, fields, models
from odoo.fields import Domain

from .. import const


class StockPutInPack(models.TransientModel):
    _inherit = 'stock.put.in.pack'

    neoship_package_type_ids = fields.Many2many('stock.package.type', compute='_compute_neoship_package_type_ids')

    @api.depends('move_line_ids', 'package_ids', 'package_carrier_type')
    def _compute_neoship_package_type_ids(self):
        package_types = self.env['stock.package.type']
        for wizard in self:
            if wizard.package_carrier_type != const.DELIVERY_TYPE:
                wizard.neoship_package_type_ids = package_types
                continue
            picking = (wizard.move_line_ids | wizard.package_ids.move_line_ids).picking_id
            if len(picking) == 1:
                domain = Domain(picking._neoship_package_type_domain())
            else:
                domain = Domain('package_carrier_type', '=', const.DELIVERY_TYPE)
            # Neoship gets no box dimensions, so warehouse boxes without a carrier integration fit too.
            domain |= Domain('package_carrier_type', '=', const.ODOO_PACKAGE_CARRIER_TYPE_NONE)
            wizard.neoship_package_type_ids = package_types.search(domain)
