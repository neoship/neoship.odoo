from datetime import timedelta
from unittest.mock import patch

import requests
from lxml import etree

from odoo import fields
from odoo.tests import tagged
from odoo.tools.safe_eval import safe_eval

from odoo.addons.delivery_neoship import const
from odoo.addons.delivery_neoship.models.neoship_api import TEST_URL

from .common import NeoshipCommon, login_ok, make_response, mock_neoship

LOGGER = 'odoo.addons.delivery_neoship.models.neoship_parcel'
SPS = {'id': 2, 'name': 'SPS', 'shortcut': 'SPS'}
STATUS_EXPORTED = {'id': 205, 'name': 'Exportovaná', 'group': 'exported'}
STATUS_DATA_DEFINED = {'id': 107, 'name': 'Definícia dát', 'group': None}
STATUS_TRANSIT = {'id': 109, 'name': 'Prvá registrácia', 'group': 'transit'}
STATUS_DELIVERED = {'id': 120, 'name': 'Doručená', 'group': 'delivered'}
STATUS_NOT_DELIVERED = {'id': 129, 'name': 'Adresát neznámy', 'group': 'notdelivered'}
STATUS_CANCEL = {'id': 256, 'name': 'Stornovať', 'group': 'cancel'}
STATUS_RETURNED = {'id': 140, 'name': 'Vrátená odosielateľovi', 'group': 'returned'}


def parcel(record, status):
    return {
        'id': record.neoship_id,
        'reference_number': record.reference,
        'tracking_number': record.tracking_ref,
        'last_status': status,
        'shipper': SPS,
    }


def shipment(picking, status):
    return {
        'id': picking.neoship_parcel_ids.neoship_id,
        'reference_number': picking.neoship_parcel_ids.reference,
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
        cls.env['neoship.parcel'].search([]).write({'status_group': const.STATUS_GROUP_DELIVERED})

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
                'carrier_tracking_ref': f'TRK{package_id}',
            }
        )
        self.env['neoship.parcel'].create(
            {
                'picking_id': picking.id,
                'neoship_id': package_id,
                'reference': f'REF-{package_id}',
                'tracking_ref': f'TRK{package_id}',
            }
        )
        return picking

    def _shipped_in_packs(self, count):
        picking = self._shipped()
        main = picking.neoship_parcel_ids
        package_id, main_reference = main.neoship_id, main.reference
        main.unlink()
        product = self.env['product.product'].create({'name': 'Packed item', 'type': 'consu'})
        move = self.env['stock.move'].create(
            {
                'picking_id': picking.id,
                'product_id': product.id,
                'product_uom_qty': count,
                'location_id': self.out_type.default_location_src_id.id,
                'location_dest_id': self.env.ref('stock.stock_location_customers').id,
            }
        )
        trackings = []
        for sequence in range(1, count + 1):
            reference = main_reference if sequence == 1 else f'{main_reference}{sequence - 1}'
            tracking = f'{picking.carrier_tracking_ref}-{sequence}'
            pack = self.env['stock.package'].create({'name': f'PACK-{picking.id}-{sequence}'})
            self.env['neoship.parcel'].create(
                {
                    'picking_id': picking.id,
                    'package_id': pack.id,
                    'sequence': sequence,
                    'neoship_id': package_id + 1000 * (sequence - 1),
                    'reference': reference,
                    'tracking_ref': tracking,
                }
            )
            self.env['stock.move.line'].create(
                {
                    'move_id': move.id,
                    'picking_id': picking.id,
                    'product_id': product.id,
                    'quantity': 1,
                    'location_id': move.location_id.id,
                    'location_dest_id': move.location_dest_id.id,
                    'result_package_id': pack.id,
                }
            )
            trackings.append(tracking)
        picking.carrier_tracking_ref = ','.join(trackings)
        return picking, picking.neoship_parcel_ids

    def _sync(self, *responses, pickings=None):
        with mock_neoship(*responses) as calls:
            if pickings is None:
                self.env['neoship.parcel']._cron_update_tracking()
            else:
                pickings.action_neoship_update_tracking()
        return calls

    def _found(self, *shipments):
        return make_response(json_data=list(shipments))

    def test_cron_stores_status_and_delivery_group(self):
        in_transit, delivered = self._shipped(), self._shipped()
        calls = self._sync(
            login_ok(),
            self._found(shipment(in_transit, STATUS_TRANSIT), shipment(delivered, STATUS_DELIVERED)),
        )

        self.assertTrue(calls[1]['url'].endswith('/package/referencenumber/'))
        self.assertEqual(
            sorted(calls[1]['json']['reference_numbers']),
            sorted([in_transit.neoship_parcel_ids.reference, delivered.neoship_parcel_ids.reference]),
        )
        self.assertEqual(in_transit.neoship_status, 'Prvá registrácia')
        self.assertEqual(in_transit.neoship_parcel_ids.status_id, 109)
        self.assertEqual(in_transit.neoship_status_group, const.STATUS_GROUP_TRANSIT)
        self.assertTrue(in_transit.neoship_parcel_ids.status_date)
        self.assertTrue(in_transit.neoship_parcel_ids.last_sync)
        self.assertEqual(delivered.neoship_status_group, const.STATUS_GROUP_DELIVERED)
        self.assertIn('Doručená', delivered.message_ids[0].body)

    def test_finished_shipments_are_no_longer_tracked(self):
        delivered, in_transit = self._shipped(), self._shipped()
        self._sync(
            login_ok(),
            self._found(shipment(delivered, STATUS_DELIVERED), shipment(in_transit, STATUS_TRANSIT)),
        )
        (delivered | in_transit).neoship_parcel_ids.last_sync = fields.Datetime.now() - timedelta(hours=3)
        calls = self._sync(
            login_ok(),
            self._found(shipment(in_transit, STATUS_TRANSIT)),
        )
        self.assertEqual(calls[1]['json']['reference_numbers'], [in_transit.neoship_parcel_ids.reference])

    def test_unchanged_status_keeps_its_change_date(self):
        picking = self._shipped()
        responses = (
            login_ok(),
            self._found(shipment(picking, STATUS_TRANSIT)),
        )
        self._sync(*responses, pickings=picking)
        picking.neoship_parcel_ids.status_date = fields.Datetime.now() - timedelta(days=2)
        changed = picking.neoship_parcel_ids.status_date
        self._sync(
            login_ok(),
            self._found(shipment(picking, STATUS_TRANSIT)),
            pickings=picking,
        )
        self.assertEqual(picking.neoship_parcel_ids.status_date, changed)
        self.assertEqual(len(picking.message_ids.filtered(lambda message: 'Prvá registrácia' in message.body)), 1)

    def test_shipment_without_status_change_stops_after_tracking_days(self):
        self.env['ir.config_parameter'].sudo().set_param(const.TRACKING_DAYS_PARAM, '10')
        recent, stale = self._shipped(days_ago=9), self._shipped(days_ago=11)
        stale_with_new_status = self._shipped(days_ago=20)
        stale_with_new_status.neoship_parcel_ids.status_date = fields.Datetime.now() - timedelta(days=1)
        calls = self._sync(
            login_ok(),
            self._found(shipment(recent, STATUS_TRANSIT), shipment(stale_with_new_status, STATUS_TRANSIT)),
        )
        self.assertNotIn(stale.neoship_parcel_ids.reference, calls[1]['json']['reference_numbers'])
        self.assertIn(recent.neoship_parcel_ids.reference, calls[1]['json']['reference_numbers'])
        self.assertIn(stale_with_new_status.neoship_parcel_ids.reference, calls[1]['json']['reference_numbers'])

    def test_exported_shipment_keeps_tracking(self):
        picking = self._shipped()
        self._sync(
            login_ok(),
            self._found(shipment(picking, STATUS_EXPORTED)),
        )
        self.assertEqual(picking.neoship_status, 'Exportovaná')
        self.assertEqual(picking.neoship_status_group, const.STATUS_GROUP_EXPORTED)
        self.assertIn(picking, self._tracked_pickings())

    def test_status_without_group_keeps_tracking(self):
        picking = self._shipped()
        self._sync(
            login_ok(),
            self._found(shipment(picking, STATUS_DATA_DEFINED)),
        )
        self.assertEqual(picking.neoship_status, 'Definícia dát')
        self.assertFalse(picking.neoship_status_group)
        self.assertIn(picking, self._tracked_pickings())

    def test_shipment_missing_from_reference_lookup_is_read_by_id(self):
        picking = self._shipped()
        calls = self._sync(
            login_ok(),
            make_response(404, {}),
            make_response(json_data=shipment(picking, STATUS_NOT_DELIVERED)),
        )
        self.assertTrue(calls[-1]['url'].endswith(f'/package/{picking.neoship_parcel_ids.neoship_id}'))
        self.assertEqual(picking.neoship_status_group, const.STATUS_GROUP_NOT_DELIVERED)

    def test_shipment_unknown_to_neoship_is_a_tracking_error(self):
        picking = self._shipped()
        with self.assertLogs(LOGGER, 'WARNING') as logs:
            self._sync(
                login_ok(),
                make_response(404, {}),
                make_response(404, {}),
            )
        parcel_id = picking.neoship_parcel_ids.neoship_id
        self.assertIn(f'{picking.carrier_tracking_ref} (package {parcel_id}', logs.output[0])
        self.assertIn(f'{picking.carrier_tracking_ref} was not found', picking.neoship_parcel_ids.sync_error)
        self.assertTrue(picking.neoship_parcel_ids.last_sync)

    def test_unreadable_response_is_a_tracking_error_and_ends_the_run_normally(self):
        picking = self._shipped()
        with self.assertLogs(LOGGER, 'INFO') as logs:
            self._sync(
                login_ok(),
                make_response(content=b'<html>Maintenance</html>', content_type='text/html'),
            )
        self.assertIn('invalid JSON in response to POST /package/referencenumber/', logs.output[0])
        self.assertIn('1 checked, 0 changed, 1 failed', logs.output[-1])
        self.assertIn('cannot be processed', picking.neoship_parcel_ids.sync_error)
        self.assertTrue(picking.neoship_parcel_ids.last_sync)

    def test_shipment_cancelled_in_neoship_is_no_longer_tracked(self):
        picking = self._shipped()
        self._sync(
            login_ok(),
            self._found(shipment(picking, STATUS_CANCEL)),
        )
        self.assertEqual(picking.neoship_status_group, const.STATUS_GROUP_CANCEL)
        self.assertNotIn(picking, self._tracked_pickings())

    def test_failing_account_does_not_block_other_delivery_methods(self):
        other_carrier = self.carrier.copy({'name': 'Neoship Other', 'neoship_shipper_id': 2})
        other_carrier.sudo().write({'neoship_username': 'other@example.com', 'neoship_password': 'other-password'})
        failing, working = self._shipped(), self._shipped(carrier=other_carrier)
        failing.neoship_parcel_ids.sync_error = False
        with self.assertLogs(LOGGER, 'INFO') as logs:
            self._sync(
                make_response(500, {'message': 'Server down'}),
                login_ok(),
                self._found(shipment(working, STATUS_TRANSIT)),
            )
        self.assertIn('failed for delivery method Neoship Test (test): HTTP 500: Server down', logs.output[0])
        self.assertIn('2 checked, 1 changed, 1 failed', logs.output[-1])
        self.assertIn('Server down', failing.neoship_parcel_ids.sync_error)
        self.assertFalse(failing.neoship_status)
        self.assertTrue(failing.neoship_parcel_ids.last_sync)
        self.assertEqual(working.neoship_status_group, const.STATUS_GROUP_TRANSIT)
        self.assertFalse(working.neoship_parcel_ids.sync_error)

    def test_cron_logs_run_summary(self):
        changed, unchanged = self._shipped(), self._shipped()
        unchanged.neoship_parcel_ids.write({'status_id': STATUS_TRANSIT['id'], 'status': STATUS_TRANSIT['name']})
        with self.assertLogs(LOGGER, 'INFO') as logs:
            self._sync(
                login_ok(),
                self._found(shipment(changed, STATUS_DELIVERED), shipment(unchanged, STATUS_TRANSIT)),
            )
        self.assertEqual(logs.output, [f'INFO:{LOGGER}:Neoship tracking: 2 checked, 1 changed, 0 failed'])

    def test_cron_reports_progress_to_odoo(self):
        first, second = self._shipped(), self._shipped()
        cron = self.env.ref('delivery_neoship.ir_cron_neoship_update_tracking')
        with (
            patch.object(type(self.env['ir.cron']), '_commit_progress', autospec=True) as progress,
            mock_neoship(
                login_ok(),
                self._found(shipment(first, STATUS_TRANSIT), shipment(second, STATUS_TRANSIT)),
            ),
        ):
            self.env['neoship.parcel'].with_context(cron_id=cron.id)._cron_update_tracking()
        self.assertEqual(progress.call_args_list[0].kwargs, {'remaining': 2})
        self.assertEqual(progress.call_args_list[1].args[1:], (2,))

    def test_manual_update_does_not_report_cron_progress(self):
        picking = self._shipped()
        with patch.object(type(self.env['ir.cron']), '_commit_progress', autospec=True) as progress:
            self._sync(
                login_ok(),
                self._found(shipment(picking, STATUS_TRANSIT)),
                pickings=picking,
            )
        progress.assert_not_called()

    def test_tracking_stops_when_cron_time_is_spent(self):
        first, second = self._shipped(), self._shipped()
        with (
            patch.object(const, 'TRACKING_BATCH_SIZE', 1),
            mock_neoship(login_ok(), self._found(shipment(first, STATUS_TRANSIT))) as calls,
        ):
            run = (first | second).neoship_parcel_ids._update_tracking(on_batch=lambda processed: 0)
        self.assertEqual(len(calls), 2)
        self.assertEqual(first.neoship_status_group, const.STATUS_GROUP_TRANSIT)
        self.assertFalse(second.neoship_parcel_ids.last_sync)
        self.assertEqual(run.checked, 1)

    def test_cron_skips_shipments_synced_recently(self):
        recent, due = self._shipped(), self._shipped()
        now = fields.Datetime.now()
        recent.neoship_parcel_ids.last_sync = now - timedelta(minutes=const.TRACKING_RECHECK_MINUTES - 1)
        due.neoship_parcel_ids.last_sync = now - timedelta(minutes=const.TRACKING_RECHECK_MINUTES + 1)
        calls = self._sync(login_ok(), self._found(shipment(due, STATUS_TRANSIT)))
        self.assertEqual(calls[1]['json']['reference_numbers'], [due.neoship_parcel_ids.reference])

    def test_lost_connection_fails_only_unsynced_shipments_and_ends_cron_run(self):
        other_carrier = self.carrier.copy({'name': 'Neoship Other', 'neoship_shipper_id': 2})
        other_carrier.sudo().write({'neoship_username': 'other@example.com', 'neoship_password': 'other-password'})
        synced, timed_out, not_reached = self._shipped(), self._shipped(), self._shipped()
        untouched = self._shipped(carrier=other_carrier)
        cron = self.env.ref('delivery_neoship.ir_cron_neoship_update_tracking')
        with (
            patch.object(const, 'TRACKING_BATCH_SIZE', 1),
            patch.object(type(self.env['ir.cron']), '_commit_progress', autospec=True, return_value=60.0) as progress,
            mock_neoship(
                login_ok(),
                self._found(shipment(synced, STATUS_TRANSIT)),
                requests.exceptions.Timeout(),
            ),
            self.assertLogs(LOGGER, 'INFO') as logs,
        ):
            self.env['neoship.parcel'].with_context(cron_id=cron.id)._cron_update_tracking()
        self.assertEqual(synced.neoship_status_group, const.STATUS_GROUP_TRANSIT)
        self.assertFalse(synced.neoship_parcel_ids.sync_error)
        for picking in timed_out | not_reached:
            self.assertIn('did not respond in time', picking.neoship_parcel_ids.sync_error)
        self.assertFalse(untouched.neoship_parcel_ids.last_sync)
        self.assertEqual(progress.call_args_list[-1].kwargs, {'remaining': 0})
        self.assertIn('3 checked, 1 changed, 2 failed', logs.output[-1])

    def test_successful_sync_clears_previous_tracking_error(self):
        picking = self._shipped()
        picking.neoship_parcel_ids.sync_error = 'Old error'
        picking.neoship_parcel_ids.error = 'The Neoship label could not be downloaded'
        self._sync(
            login_ok(),
            self._found(shipment(picking, STATUS_TRANSIT)),
            pickings=picking,
        )
        self.assertFalse(picking.neoship_parcel_ids.sync_error)
        self.assertEqual(picking.neoship_parcel_ids.error, 'The Neoship label could not be downloaded')

    def test_shipment_is_tracked_in_its_own_environment(self):
        picking = self._shipped()
        self.carrier.prod_environment = True
        calls = self._sync(
            login_ok(),
            self._found(shipment(picking, STATUS_TRANSIT)),
            pickings=picking,
        )
        self.assertTrue(calls[-1]['url'].startswith(TEST_URL))

    def test_cancelled_shipment_clears_tracking(self):
        picking = self._shipped()
        self._sync(
            login_ok(),
            self._found(shipment(picking, STATUS_NOT_DELIVERED)),
            pickings=picking,
        )
        with mock_neoship(login_ok(), make_response(json_data={})):
            picking.cancel_shipment()
        self.assertFalse(picking.neoship_parcel_ids)
        self.assertFalse(picking.neoship_status)
        self.assertFalse(picking.neoship_status_group)

    def test_unknown_status_group_is_ignored(self):
        picking = self._shipped()
        self._sync(
            login_ok(),
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
            picking.neoship_parcel_ids.status_group = group
        candidates = self.env['stock.picking'].union(*pickings.values(), self._shipped())

        self.assertEqual(sorted(filters.values()), sorted(const.STATUS_GROUPS))
        for name, group in filters.items():
            self.assertEqual(self._filter(name) & candidates, pickings[group], name)

    def _filter(self, name):
        arch = self.env['stock.picking'].get_view(self.env.ref('stock.view_picking_internal_search').id, 'search')[
            'arch'
        ]
        domain = etree.fromstring(arch).xpath(f"//filter[@name='{name}']")[0].get('domain')
        return self.env['stock.picking'].search(safe_eval(domain))

    def _tracked_pickings(self):
        domain = self.env['neoship.parcel']._tracking_domain(fields.Datetime.now() - timedelta(days=30))
        return self.env['neoship.parcel'].search(domain).picking_id

    def test_each_pack_gets_its_status_and_the_transfer_the_least_advanced_one(self):
        picking, packs = self._shipped_in_packs(2)
        calls = self._sync(
            login_ok(),
            self._found(parcel(packs[0], STATUS_DELIVERED), parcel(packs[1], STATUS_TRANSIT)),
            pickings=picking,
        )
        self.assertEqual(calls[1]['json']['reference_numbers'], packs.mapped('reference'))
        self.assertEqual(packs.mapped('status_group'), [const.STATUS_GROUP_DELIVERED, const.STATUS_GROUP_TRANSIT])
        self.assertEqual(packs.mapped('status'), ['Doručená', 'Prvá registrácia'])
        self.assertEqual(picking.neoship_status_group, const.STATUS_GROUP_TRANSIT)
        self.assertEqual(
            picking.neoship_status,
            f'{packs[0].tracking_ref}: Doručená; {packs[1].tracking_ref}: Prvá registrácia',
        )

        self._sync(
            login_ok(),
            self._found(parcel(packs[0], STATUS_DELIVERED), parcel(packs[1], STATUS_DELIVERED)),
            pickings=picking,
        )
        self.assertEqual(picking.neoship_status_group, const.STATUS_GROUP_DELIVERED)

    def test_cron_splits_lookup_by_parcel_reference_count(self):
        singles = self.env['stock.picking'].union(*(self._shipped() for _ in range(const.TRACKING_BATCH_SIZE - 1)))
        picking, packs = self._shipped_in_packs(2)
        with self.assertLogs(LOGGER, 'INFO') as logs:
            calls = self._sync(
                login_ok(),
                self._found(
                    *(shipment(single, STATUS_DELIVERED) for single in singles),
                    parcel(packs[0], STATUS_DELIVERED),
                ),
                self._found(parcel(packs[1], STATUS_TRANSIT)),
            )

        self.assertEqual(len(calls), 3)
        self.assertEqual(
            calls[1]['json']['reference_numbers'],
            [*singles.neoship_parcel_ids.mapped('reference'), packs[0].reference],
        )
        self.assertEqual(calls[2]['json']['reference_numbers'], [packs[1].reference])
        self.assertEqual(singles.mapped('neoship_status_group'), [const.STATUS_GROUP_DELIVERED] * len(singles))
        self.assertEqual(packs.mapped('status_group'), [const.STATUS_GROUP_DELIVERED, const.STATUS_GROUP_TRANSIT])
        self.assertEqual(picking.neoship_status_group, const.STATUS_GROUP_TRANSIT)
        self.assertFalse(any((singles | picking).neoship_parcel_ids.mapped('sync_error')))
        self.assertEqual(
            logs.output,
            [f'INFO:{LOGGER}:Neoship tracking: {len(singles) + 2} checked, {len(singles) + 2} changed, 0 failed'],
        )

    def test_single_picking_with_more_than_one_lookup_batch(self):
        picking, packs = self._shipped_in_packs(const.TRACKING_BATCH_SIZE + 1)
        calls = self._sync(
            login_ok(),
            self._found(*(parcel(pack, STATUS_DELIVERED) for pack in packs[:-1])),
            self._found(parcel(packs[-1], STATUS_TRANSIT)),
            pickings=picking,
        )

        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[1]['json']['reference_numbers'], packs[:-1].mapped('reference'))
        self.assertEqual(calls[2]['json']['reference_numbers'], [packs[-1].reference])
        self.assertEqual(
            packs.mapped('status_group'),
            [const.STATUS_GROUP_DELIVERED] * const.TRACKING_BATCH_SIZE + [const.STATUS_GROUP_TRANSIT],
        )
        self.assertEqual(picking.neoship_status_group, const.STATUS_GROUP_TRANSIT)
        self.assertFalse(any(picking.neoship_parcel_ids.mapped('sync_error')))

    def test_returned_pack_keeps_tracking_the_other_packs(self):
        picking, packs = self._shipped_in_packs(3)
        self._sync(
            login_ok(),
            self._found(
                parcel(packs[0], STATUS_RETURNED), parcel(packs[1], STATUS_TRANSIT), parcel(packs[2], STATUS_TRANSIT)
            ),
            pickings=picking,
        )
        self.assertEqual(picking.neoship_status_group, const.STATUS_GROUP_TRANSIT)
        self.assertIn(f'{packs[0].tracking_ref}: Vrátená odosielateľovi', picking.neoship_status)
        self.assertIn(picking, self._tracked_pickings())

        self._sync(
            login_ok(),
            self._found(
                parcel(packs[0], STATUS_RETURNED),
                parcel(packs[1], STATUS_DELIVERED),
                parcel(packs[2], STATUS_DELIVERED),
            ),
            pickings=picking,
        )
        self.assertEqual(picking.neoship_status_group, const.STATUS_GROUP_RETURNED)
        self.assertNotIn(picking, self._tracked_pickings())

    def test_not_delivered_pack_is_the_transfer_status_while_others_move(self):
        picking, packs = self._shipped_in_packs(2)
        self._sync(
            login_ok(),
            self._found(parcel(packs[0], STATUS_NOT_DELIVERED), parcel(packs[1], STATUS_TRANSIT)),
            pickings=picking,
        )
        self.assertEqual(picking.neoship_status_group, const.STATUS_GROUP_NOT_DELIVERED)
        self.assertIn(picking, self._tracked_pickings())

    def test_pack_missing_from_lookup_keeps_its_last_status(self):
        picking, packs = self._shipped_in_packs(2)
        packs[1].write({'status': 'Prvá registrácia', 'status_group': const.STATUS_GROUP_TRANSIT})
        with self.assertLogs(LOGGER, 'WARNING'):
            calls = self._sync(
                login_ok(),
                self._found(parcel(packs[0], STATUS_DELIVERED)),
                make_response(404, {}),
                pickings=picking,
            )
        self.assertTrue(calls[-1]['url'].endswith(f'/package/{packs[1].neoship_id}'))
        self.assertEqual(packs[1].status_group, const.STATUS_GROUP_TRANSIT)
        self.assertIn('was not found', packs[1].sync_error)
        self.assertEqual(picking.neoship_status_group, const.STATUS_GROUP_TRANSIT)
