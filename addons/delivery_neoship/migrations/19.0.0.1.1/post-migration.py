from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    # The cron is noupdate, so the move of tracking from stock.picking to neoship.parcel has to be applied here.
    env = api.Environment(cr, SUPERUSER_ID, {})
    cron = env.ref('delivery_neoship.ir_cron_neoship_update_tracking', raise_if_not_found=False)
    if cron:
        cron.write(
            {'model_id': env.ref('delivery_neoship.model_neoship_parcel').id, 'code': 'model._cron_update_tracking()'}
        )
