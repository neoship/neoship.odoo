import base64
from datetime import date, datetime, timedelta

import requests
from freezegun import freeze_time

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from odoo.addons.delivery_neoship import const

from .common import NeoshipCommon, make_response, mock_neoship

LOGIN_OK = {'token': 'token-1'}
PDF = b'%PDF-1.4 protocol'
# Wednesday, 15:30 in Europe/Bratislava (CEST)
NOW = datetime(2026, 10, 7, 13, 30)
TODAY = date(2026, 10, 7)


def closure_response(**data):
    return make_response(json_data=data)


@tagged('post_install', '-at_install')
class TestClosure(NeoshipCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.carrier.write({'neoship_shipper_id': 2, 'neoship_shipper_code': 'SPS', 'neoship_shipper_name': 'SPS'})
        cls.packeta = cls.carrier.copy(
            {
                'name': 'Neoship Packeta',
                'neoship_username': 'user@example.com',
                'neoship_password': 'secret-password',
                'neoship_shipper_id': 3,
                'neoship_shipper_code': 'Packeta',
                'neoship_shipper_name': 'Packeta',
                'neoship_carrier_type': 131,
            }
        )
        cls.sk_posta = cls.carrier.copy(
            {
                'name': 'Neoship SK Posta',
                'neoship_username': 'user@example.com',
                'neoship_password': 'secret-password',
                'neoship_shipper_id': 7,
                'neoship_shipper_code': 'SK_POSTA',
                'neoship_shipper_name': 'Slovenská pošta',
            }
        )

    def _schedule(self, carrier=None, **vals):
        return self.env['neoship.closure.schedule'].create(
            {'carrier_id': (carrier or self.carrier).id, 'tz': 'Europe/Bratislava', **vals}
        )

    def _close(self, schedule, *responses):
        with freeze_time(NOW), mock_neoship(make_response(json_data=LOGIN_OK), *responses) as calls:
            schedule.action_close_now()
        return calls, schedule.closure_ids[:1]

    def test_only_carriers_with_closure_can_be_scheduled(self):
        self.assertTrue(self.carrier.neoship_has_closure)
        gls = self.carrier.copy({'neoship_shipper_code': 'GLS', 'neoship_shipper_name': 'GLS'})
        self.assertFalse(gls.neoship_has_closure)
        with self.assertRaises(ValidationError):
            self._schedule(gls)

    def test_schedule_runs_daily_at_local_time(self):
        with freeze_time(NOW):
            schedule = self._schedule(closure_time=15.0)
            cron = schedule.cron_id
            self.assertTrue(cron.active)
            self.assertEqual(cron.interval_type, const.ODOO_CRON_INTERVAL_DAYS)
            self.assertEqual(cron.interval_number, 1)
            # 15:00 CEST has passed today, so the first run is tomorrow at 13:00 UTC.
            self.assertEqual(cron.nextcall, datetime(2026, 10, 8, 13, 0))
            self.assertEqual(cron.code, f'model.browse({schedule.id})._run_scheduled()')

            schedule.closure_time = 16.5
            self.assertEqual(cron.nextcall, datetime(2026, 10, 7, 14, 30))

        schedule.active = False
        self.assertFalse(cron.active)

        server_action = cron.ir_actions_server_id
        schedule.unlink()
        self.assertFalse(cron.exists())
        self.assertFalse(server_action.exists())

    def test_sps_closure_stores_protocol(self):
        calls, closure = self._close(
            self._schedule(),
            closure_response(errors='', protocol=base64.encodebytes(PDF).decode()),
        )
        self.assertEqual(calls[1]['url'].rsplit('/api', 1)[1], '/package/bulk/')
        self.assertEqual(calls[1]['json'], {'action': 'daily_closing'})
        self.assertEqual(calls[1]['timeout'], const.CLOSURE_TIMEOUT)
        self.assertEqual(closure.state, const.CLOSURE_STATE_DONE)
        self.assertEqual(base64.b64decode(closure.protocol), PDF)
        self.assertEqual(closure.protocol_filename, 'SPS-protocol-2026-10-07.pdf')
        self.assertEqual(closure.closure_date, TODAY)
        self.assertFalse(closure.message)

    def test_first_packeta_closure_sends_today_and_keeps_skipped(self):
        calls, closure = self._close(
            self._schedule(self.packeta),
            closure_response(
                protocol=base64.b64encode(PDF).decode(),
                skipped=['WH-OUT-00001'],
                errors='Tieto zásielky nie sú na dodacom liste, Packeta ich už prevzala: WH-OUT-00001',
            ),
        )
        self.assertEqual(calls[1]['json'], {'action': 'packeta_acceptance_protocol', 'date': '2026-10-07'})
        self.assertEqual(closure.state, const.CLOSURE_STATE_DONE)
        self.assertEqual(closure.date_from, TODAY)
        self.assertIn('WH-OUT-00001', closure.message)

    def test_sk_posta_closure_without_protocol_is_closed(self):
        calls, closure = self._close(
            self._schedule(self.sk_posta),
            closure_response(errors='', protocol='', package_ids=[11, 12, 13]),
        )
        self.assertEqual(calls[1]['json'], {'action': 'SK_POSTA_daily_closing'})
        self.assertEqual(closure.state, const.CLOSURE_STATE_DONE)
        self.assertFalse(closure.protocol)

    def test_nothing_to_close(self):
        _calls, closure = self._close(self._schedule(), closure_response(errors=const.CLOSURE_NO_PACKAGES))
        self.assertEqual(closure.state, const.CLOSURE_STATE_EMPTY)
        self.assertFalse(closure.message)

    def test_carrier_error_is_recorded(self):
        response = closure_response(errors='SPS: invalid credentials', protocol='')
        _calls, closure = self._close(self._schedule(), response)
        self.assertEqual(closure.state, const.CLOSURE_STATE_FAILED)
        self.assertEqual(closure.message, 'SPS: invalid credentials')

    def test_http_error_is_recorded_without_password(self):
        _calls, closure = self._close(self._schedule(), make_response(500, {'message': 'Internal error'}))
        self.assertEqual(closure.state, const.CLOSURE_STATE_FAILED)
        self.assertIn('Internal error', closure.message)
        self.assertNotIn('secret-password', closure.message)

    def test_timeout_is_recorded(self):
        _calls, closure = self._close(self._schedule(), requests.exceptions.ReadTimeout())
        self.assertEqual(closure.state, const.CLOSURE_STATE_FAILED)
        self.assertIn('did not respond in time', closure.message)

    def test_carrier_without_closure_fails_without_calling_neoship(self):
        schedule = self._schedule()
        self.carrier.write({'neoship_shipper_code': 'GLS', 'neoship_shipper_name': 'GLS'})
        with freeze_time(NOW), mock_neoship() as calls:
            schedule.action_close_now()
        self.assertFalse(calls)
        self.assertEqual(schedule.closure_ids.state, const.CLOSURE_STATE_FAILED)

    def test_scheduled_run_skips_disabled_weekday(self):
        schedule = self._schedule(wed=False)
        with freeze_time(NOW), mock_neoship() as calls:
            schedule._run_scheduled()
        self.assertFalse(calls)
        self.assertFalse(schedule.closure_ids)

    def _past_closure(self, carrier, closure_date, state=const.CLOSURE_STATE_DONE):
        return self.env['neoship.closure'].create(
            {
                'carrier_id': carrier.id,
                'action': carrier._neoship_closure_action(),
                'prod_environment': carrier.prod_environment,
                'closure_date': closure_date,
                'closed_at': datetime.combine(closure_date, datetime.min.time()),
                'state': state,
            }
        )

    def test_packeta_closure_sends_date_of_last_closure(self):
        packeta_cz = self.packeta.copy({'name': 'Neoship Packeta CZ', 'neoship_carrier_type': 14})
        self._past_closure(packeta_cz, date(2026, 10, 2))
        self._past_closure(self.packeta, date(2026, 10, 5), const.CLOSURE_STATE_EMPTY)
        self._past_closure(self.packeta, date(2026, 10, 6), const.CLOSURE_STATE_FAILED)
        calls, closure = self._close(self._schedule(self.packeta), closure_response(protocol=''))
        self.assertEqual(calls[1]['json']['date'], '2026-10-02', 'Shipments after the last closure are not lost.')
        self.assertEqual(closure.date_from, date(2026, 10, 2))

    def test_packeta_closure_looks_back_at_most_a_week(self):
        self._past_closure(self.packeta, date(2026, 9, 1))
        calls, _closure = self._close(self._schedule(self.packeta), closure_response(protocol=''))
        self.assertEqual(calls[1]['json']['date'], str(TODAY - timedelta(days=const.CLOSURE_MAX_DAYS)))

    def test_delivery_method_can_close_several_times_a_day(self):
        morning = self._schedule(self.packeta, closure_time=11.0)
        evening = self._schedule(self.packeta, closure_time=20.0)
        protocol = closure_response(protocol=base64.b64encode(PDF).decode())
        with freeze_time(datetime(2026, 10, 7, 9, 0)), mock_neoship(make_response(json_data=LOGIN_OK), protocol):
            morning._run_scheduled()
        with (
            freeze_time(datetime(2026, 10, 7, 18, 0)),
            mock_neoship(make_response(json_data=LOGIN_OK), protocol) as calls,
        ):
            evening._run_scheduled()
        self.assertEqual(calls[1]['json']['date'], '2026-10-07')
        self.assertEqual(evening.closure_ids.state, const.CLOSURE_STATE_DONE)

    def test_scheduled_run_skips_an_account_closed_minutes_ago(self):
        packeta_sk = self._schedule(self.packeta)
        packeta_cz = self._schedule(self.packeta.copy({'name': 'Neoship Packeta CZ', 'neoship_carrier_type': 14}))
        protocol = closure_response(protocol=base64.b64encode(PDF).decode())
        with freeze_time(NOW), mock_neoship(make_response(json_data=LOGIN_OK), protocol) as calls:
            packeta_sk._run_scheduled()
            packeta_cz._run_scheduled()
        self.assertEqual(len(calls), 2)
        self.assertFalse(packeta_cz.closure_ids)

        with freeze_time(NOW), mock_neoship(make_response(json_data=LOGIN_OK), protocol) as calls:
            packeta_cz.action_close_now()
        self.assertEqual(len(calls), 2, 'A manual closure runs even when the account was just closed.')

        later = NOW + timedelta(minutes=const.CLOSURE_DEDUP_MINUTES + 1)
        with freeze_time(later), mock_neoship(make_response(json_data=LOGIN_OK), protocol) as calls:
            packeta_sk._run_scheduled()
        self.assertEqual(len(calls), 2)

    def test_failed_closure_does_not_block_next_run(self):
        schedule = self._schedule()
        with freeze_time(NOW), mock_neoship(make_response(json_data=LOGIN_OK), closure_response(errors='down')):
            schedule._run_scheduled()
        with (
            freeze_time(NOW),
            mock_neoship(make_response(json_data=LOGIN_OK), closure_response(protocol=base64.b64encode(PDF).decode())),
        ):
            schedule._run_scheduled()
        self.assertEqual(
            schedule.closure_ids.sorted('id').mapped('state'), [const.CLOSURE_STATE_FAILED, const.CLOSURE_STATE_DONE]
        )
