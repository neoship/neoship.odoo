from odoo import models

from odoo.addons.delivery_neoship import const


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _neoship_delivered_quantity(self, sale_line):
        product = sale_line.product_id
        if all(move.product_id == product for move in self):
            return super()._neoship_delivered_quantity(sale_line)
        bom = self.bom_line_id.bom_id.filtered(
            lambda bom: (
                bom.type == const.ODOO_BOM_TYPE_KIT
                and (bom.product_id or bom.product_tmpl_id.product_variant_ids) & product
            )
        )[:1]
        if not bom:
            bom = self.env['mrp.bom']._bom_find(
                product, company_id=sale_line.company_id.id, bom_type=const.ODOO_BOM_TYPE_KIT
            )[product]
        if not bom:
            return super()._neoship_delivered_quantity(sale_line)
        filters = {'incoming_moves': lambda move: True, 'outgoing_moves': lambda move: False}
        ordered = sale_line.product_uom_id._compute_quantity(sale_line.product_uom_qty, bom.product_uom_id, round=False)
        kits = self._compute_kit_quantities(product, ordered, bom, filters)
        return bom.product_uom_id._compute_quantity(kits, sale_line.product_uom_id, round=False)
