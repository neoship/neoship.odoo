from datetime import timedelta
from unittest.mock import patch

from lxml import etree

from odoo import fields
from odoo.tests import tagged
from odoo.tools.safe_eval import safe_eval

from odoo.addons.delivery_neoship import const

from .common import NeoshipCommon, make_response, mock_neoship

LOGGER = 'odoo.addons.delivery_neoship.models.stock_picking'
LOGIN_OK = {'token': 'token-1'}
SPS = {'id': 2, 'name': 'SPS', 'shortcut': 'SPS'}
STATUS_EXPORTED = {'id': 205, 'name': 'Exportovaná', 'group': 'exported'}
STATUS_DATA_DEFINED = {'id': 107, 'name': 'Definícia dát', 'group': None}
STATUS_TRANSIT = {'id': 109, 'name': 'Prvá registrácia', 'group': 'transit'}
STATUS_DELIVERED = {'id': 120, 'name': 'Doručená', 'group': 'delivered'}
STATUS_NOT_DELIVERED = {'id': 129, 'name': 'Adresát neznámy', 'group': 'notdelivered'}
STATUS_CANCEL = {'id': 256, 'name': 'Stornovať', 'group': 'cancel'}


def shipment(picking, status):
    return {
        'id': picking.neoship_package_id,
        'reference_number': picking.neoship_reference,
        'tracking_number': picking.carrier_tracking_ref,
        'last_status': status,
        'shipper': SPS,
    }


@tagged('post_install', '-at_install')
class TestTracking(NeoshipCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.carrier.write({'neoship_shipper_id': 2, 'neoship_shipper_code': 'SPS', 'neoship_shipper_name': 'SPS'})
        cls.out_type = cls.env['stock.warehouse'].search([('company_id', '=', cls.env.company.id)], limit=1).out_type_id
        cls.partner = cls.env['res.partner'].create({'name': 'Jan Testovaci'})
        cls.next_package_id = 600
        # Shipments already in the database would be polled too.
        cls.env['stock.picking'].search([('neoship_package_id', '!=', False)]).write(
            {'neoship_status_group': const.STATUS_GROUP_DELIVERED}
        )

    def _shipped(self, carrier=None, days_ago=0):
        TestTracking.next_package_id += 1
        package_id = TestTracking.next_package_id
        picking = self.env['stock.picking'].create(
            {
                'picking_type_id': self.out_type.id,
                'partner_id': self.partner.id,
                'carrier_id': (carrier or self.carrier).id,
            }
        )
        picking.write(
            {
                'state': 'done',
                'date_done': fields.Datetime.now() - timedelta(days=days_ago),
                'neoship_package_id': package_id,
                'neoship_reference': f'REF-{package_id}',
                'carrier_tracking_ref': f'TRK{package_id}',
            }
        )
        return picking

    def _sync(self, *responses, pickings=None):
        with mock_neoship(*responses) as calls:
            if pickings is None:
                self.env['stock.picking']._cron_neoship_update_tracking()
            else:
                pickings.action_neoship_update_tracking()
        return calls

    def _found(self, *shipments):
        return make_response(json_data=list(shipments))

    def test_cron_stores_status_and_delivery_group(self):
        in_transit, delivered = self._shipped(), self._shipped()
        calls = self._sync(
            make_response(json_data=LOGIN_OK),
            self._found(shipment(in_transit, STATUS_TRANSIT), shipment(delivered, STATUS_DELIVERED)),
        )

        self.assertTrue(calls[1]['url'].endswith('/package/referencenumber/'))
        self.assertEqual(
            sorted(calls[1]['json']['reference_numbers']),
            sorted([in_transit.neoship_reference, delivered.neoship_reference]),
        )
        self.assertEqual(in_transit.neoship_status, 'Prvá registrácia')
        self.assertEqual(in_transit.neoship_status_id, 109)
        self.assertEqual(in_transit.neoship_status_group, const.STATUS_GROUP_TRANSIT)
        self.assertTrue(in_transit.neoship_status_date)
        self.assertTrue(in_transit.neoship_last_sync)
        self.assertEqual(delivered.neoship_status_group, const.STATUS_GROUP_DELIVERED)
        self.assertIn('Doručená', delivered.message_ids[0].body)
        self.assertEqual(in_transit.state, 'done')

    def test_finished_shipments_are_no_longer_tracked(self):
        delivered, in_transit = self._shipped(), self._shipped()
        self._sync(
            make_response(json_data=LOGIN_OK),
            self._found(shipment(delivered, STATUS_DELIVERED), shipment(in_transit, STATUS_TRANSIT)),
        )
        calls = self._sync(
            make_response(json_data=LOGIN_OK),
            self._found(shipment(in_transit, STATUS_TRANSIT)),
        )
        self.assertEqual(calls[1]['json']['reference_numbers'], [in_transit.neoship_reference])

    def test_unchanged_status_keeps_its_change_date(self):
        picking = self._shipped()
        responses = (
            make_response(json_data=LOGIN_OK),
            self._found(shipment(picking, STATUS_TRANSIT)),
        )
        self._sync(*responses, pickings=picking)
        picking.neoship_status_date = fields.Datetime.now() - timedelta(days=2)
        changed = picking.neoship_status_date
        self._sync(
            make_response(json_data=LOGIN_OK),
            self._found(shipment(picking, STATUS_TRANSIT)),
            pickings=picking,
        )
        self.assertEqual(picking.neoship_status_date, changed)
        self.assertEqual(len(picking.message_ids.filtered(lambda message: 'Prvá registrácia' in message.body)), 1)

    def test_shipment_without_status_change_stops_after_tracking_days(self):
        self.env['ir.config_parameter'].sudo().set_param(const.TRACKING_DAYS_PARAM, '10')
        recent, stale = self._shipped(days_ago=9), self._shipped(days_ago=11)
        stale_with_new_status = self._shipped(days_ago=20)
        stale_with_new_status.neoship_status_date = fields.Datetime.now() - timedelta(days=1)
        calls = self._sync(
            make_response(json_data=LOGIN_OK),
            self._found(shipment(recent, STATUS_TRANSIT), shipment(stale_with_new_status, STATUS_TRANSIT)),
        )
        self.assertNotIn(stale.neoship_reference, calls[1]['json']['reference_numbers'])
        self.assertIn(recent.neoship_reference, calls[1]['json']['reference_numbers'])
        self.assertIn(stale_with_new_status.neoship_reference, calls[1]['json']['reference_numbers'])

    def test_exported_shipment_keeps_tracking(self):
        picking = self._shipped()
        self._sync(
            make_response(json_data=LOGIN_OK),
            self._found(shipment(picking, STATUS_EXPORTED)),
        )
        self.assertEqual(picking.neoship_status, 'Exportovaná')
        self.assertEqual(picking.neoship_status_group, const.STATUS_GROUP_EXPORTED)
        self.assertIn(picking, self.env['stock.picking'].search(self._tracking_domain()))

    def test_status_without_group_keeps_tracking(self):
        picking = self._shipped()
        self._sync(
            make_response(json_data=LOGIN_OK),
            self._found(shipment(picking, STATUS_DATA_DEFINED)),
        )
        self.assertEqual(picking.neoship_status, 'Definícia dát')
        self.assertFalse(picking.neoship_status_group)
        self.assertIn(picking, self.env['stock.picking'].search(self._tracking_domain()))

    def test_shipment_missing_from_reference_lookup_is_read_by_id(self):
        picking = self._shipped()
        calls = self._sync(
            make_response(json_data=LOGIN_OK),
            make_response(404, {}),
            make_response(json_data=shipment(picking, STATUS_NOT_DELIVERED)),
        )
        self.assertTrue(calls[-1]['url'].endswith(f'/package/{picking.neoship_package_id}'))
        self.assertEqual(picking.neoship_status_group, const.STATUS_GROUP_NOT_DELIVERED)

    def test_shipment_unknown_to_neoship_is_a_tracking_error(self):
        picking = self._shipped()
        with self.assertLogs(LOGGER, 'WARNING') as logs:
            self._sync(
                make_response(json_data=LOGIN_OK),
                make_response(404, {}),
                make_response(404, {}),
            )
        self.assertIn(f'{picking.carrier_tracking_ref} (package {picking.neoship_package_id}', logs.output[0])
        self.assertIn(f'{picking.carrier_tracking_ref} was not found', picking.neoship_sync_error)
        self.assertTrue(picking.neoship_last_sync)

    def test_shipment_cancelled_in_neoship_is_no_longer_tracked(self):
        picking = self._shipped()
        self._sync(
            make_response(json_data=LOGIN_OK),
            self._found(shipment(picking, STATUS_CANCEL)),
        )
        self.assertEqual(picking.neoship_status_group, const.STATUS_GROUP_CANCEL)
        self.assertNotIn(picking, self.env['stock.picking'].search(self._tracking_domain()))

    def test_failing_account_does_not_block_other_delivery_methods(self):
        other_carrier = self.carrier.copy({'name': 'Neoship Other', 'neoship_shipper_id': 2})
        other_carrier.sudo().write({'neoship_username': 'other@example.com', 'neoship_password': 'other-password'})
        failing, working = self._shipped(), self._shipped(carrier=other_carrier)
        failing.neoship_sync_error = False
        with self.assertLogs(LOGGER, 'INFO') as logs:
            self._sync(
                make_response(500, {'message': 'Server down'}),
                make_response(json_data=LOGIN_OK),
                self._found(shipment(working, STATUS_TRANSIT)),
            )
        self.assertIn('failed for delivery method Neoship Test (test): HTTP 500: Server down', logs.output[0])
        self.assertIn('2 checked, 1 changed, 1 failed', logs.output[-1])
        self.assertIn('Server down', failing.neoship_sync_error)
        self.assertFalse(failing.neoship_status)
        self.assertTrue(failing.neoship_last_sync)
        self.assertEqual(working.neoship_status_group, const.STATUS_GROUP_TRANSIT)
        self.assertFalse(working.neoship_sync_error)

    def test_cron_logs_run_summary(self):
        changed, unchanged = self._shipped(), self._shipped()
        unchanged.write({'neoship_status_id': STATUS_TRANSIT['id'], 'neoship_status': STATUS_TRANSIT['name']})
        with self.assertLogs(LOGGER, 'INFO') as logs:
            self._sync(
                make_response(json_data=LOGIN_OK),
                self._found(shipment(changed, STATUS_DELIVERED), shipment(unchanged, STATUS_TRANSIT)),
            )
        self.assertEqual(logs.output, [f'INFO:{LOGGER}:Neoship tracking: 2 checked, 1 changed, 0 failed'])

    def test_cron_reports_progress_to_odoo(self):
        first, second = self._shipped(), self._shipped()
        cron = self.env.ref('delivery_neoship.ir_cron_neoship_update_tracking')
        with (
            patch.object(type(self.env['ir.cron']), '_commit_progress', autospec=True) as progress,
            mock_neoship(
                make_response(json_data=LOGIN_OK),
                self._found(shipment(first, STATUS_TRANSIT), shipment(second, STATUS_TRANSIT)),
            ),
        ):
            self.env['stock.picking'].with_context(cron_id=cron.id)._cron_neoship_update_tracking()
        self.assertEqual(progress.call_args_list[0].kwargs, {'remaining': 2})
        self.assertEqual(progress.call_args_list[1].args[1:], (2,))

    def test_manual_update_does_not_report_cron_progress(self):
        picking = self._shipped()
        with patch.object(type(self.env['ir.cron']), '_commit_progress', autospec=True) as progress:
            self._sync(
                make_response(json_data=LOGIN_OK),
                self._found(shipment(picking, STATUS_TRANSIT)),
                pickings=picking,
            )
        progress.assert_not_called()

    def test_successful_sync_clears_previous_tracking_error(self):
        picking = self._shipped()
        picking.neoship_sync_error = 'Old error'
        picking.neoship_error = 'The Neoship label could not be downloaded'
        self._sync(
            make_response(json_data=LOGIN_OK),
            self._found(shipment(picking, STATUS_TRANSIT)),
            pickings=picking,
        )
        self.assertFalse(picking.neoship_sync_error)
        self.assertEqual(picking.neoship_error, 'The Neoship label could not be downloaded')

    def test_shipment_is_tracked_in_its_own_environment(self):
        picking = self._shipped()
        self.carrier.prod_environment = True
        calls = self._sync(
            make_response(json_data=LOGIN_OK),
            self._found(shipment(picking, STATUS_TRANSIT)),
            pickings=picking,
        )
        self.assertIn('azurewebsites', calls[-1]['url'])

    def test_cancelled_shipment_clears_tracking(self):
        picking = self._shipped()
        self._sync(
            make_response(json_data=LOGIN_OK),
            self._found(shipment(picking, STATUS_NOT_DELIVERED)),
            pickings=picking,
        )
        with mock_neoship(make_response(json_data=LOGIN_OK), make_response(json_data={})):
            picking.cancel_shipment()
        self.assertFalse(picking.neoship_status)
        self.assertFalse(picking.neoship_status_group)
        self.assertFalse(picking.neoship_last_sync)

    def test_unknown_status_group_is_ignored(self):
        picking = self._shipped()
        self._sync(
            make_response(json_data=LOGIN_OK),
            self._found(shipment(picking, {'id': 999, 'name': 'Nový stav', 'group': 'lost_in_space'})),
        )
        self.assertEqual(picking.neoship_status, 'Nový stav')
        self.assertFalse(picking.neoship_status_group)

    def test_delivery_group_filters(self):
        filters = {
            'neoship_new': const.STATUS_GROUP_NEW,
            'neoship_exported': const.STATUS_GROUP_EXPORTED,
            'neoship_transit': const.STATUS_GROUP_TRANSIT,
            'neoship_delivered': const.STATUS_GROUP_DELIVERED,
            'neoship_not_delivered': const.STATUS_GROUP_NOT_DELIVERED,
            'neoship_returned': const.STATUS_GROUP_RETURNED,
            'neoship_cancel': const.STATUS_GROUP_CANCEL,
        }
        pickings = {group: self._shipped() for group in const.STATUS_GROUPS}
        for group, picking in pickings.items():
            picking.neoship_status_group = group
        candidates = self.env['stock.picking'].union(*pickings.values(), self._shipped())

        self.assertEqual(sorted(filters.values()), sorted(const.STATUS_GROUPS))
        for name, group in filters.items():
            self.assertEqual(self._filter(name) & candidates, pickings[group], name)

    def test_deliveries_list_shows_delivery_group(self):
        arch = self.env['stock.picking'].get_views([(False, 'list')])['views']['list']['arch']
        column = etree.fromstring(arch).xpath("//field[@name='neoship_status_group']")
        self.assertEqual(column[0].get('optional'), 'show')

    def _filter(self, name):
        arch = self.env['stock.picking'].get_view(self.env.ref('stock.view_picking_internal_search').id, 'search')[
            'arch'
        ]
        domain = etree.fromstring(arch).xpath(f"//filter[@name='{name}']")[0].get('domain')
        return self.env['stock.picking'].search(safe_eval(domain))

    def _tracking_domain(self):
        return self.env['stock.picking']._neoship_tracking_domain(fields.Datetime.now() - timedelta(days=30))
