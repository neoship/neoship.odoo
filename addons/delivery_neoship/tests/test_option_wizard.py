from odoo.exceptions import UserError, ValidationError
from odoo.tests import new_test_user, tagged

from odoo.addons.delivery_neoship import const

from .common import NeoshipCommon, make_response, mock_neoship

LOGIN_OK = {'token': 'token-1'}
ADDRESS = {'type': 'address', 'countries': ['CZ', 'SK']}
PARCELSHOP = {'type': 'parcelshop', 'countries': ['SK']}
SHIPPERS = [
    {'id': 2, 'name': 'SPS', 'shortcut': 'SPS', 'delivery_types': [ADDRESS, PARCELSHOP]},
    {'id': 3, 'name': 'Packeta', 'shortcut': 'Packeta', 'delivery_types': [ADDRESS, PARCELSHOP]},
    {'id': 4, 'name': '123kuriér', 'shortcut': '123', 'delivery_types': [ADDRESS]},
]
PACKETA_CARRIERS = [
    {
        'id': 3,
        'packeta_id': 131,
        'name': 'SK Packeta Home HD',
        'currency': 'EUR',
        'state': 'Slovensko',
        'state_code': 'SK',
        'available': True,
    },
    {
        'id': 2,
        'packeta_id': 106,
        'name': 'CZ Zásilkovna domů HD',
        'currency': 'CZK',
        'state': 'Česko',
        'state_code': 'CZ',
        'available': True,
    },
]


@tagged('post_install', '-at_install')
class TestOptionWizard(NeoshipCommon):
    def _open(self, action_name, payload, carrier=None):
        carrier = carrier or self.carrier
        with mock_neoship(make_response(json_data=LOGIN_OK), make_response(json_data=payload)) as calls:
            action = getattr(carrier, action_name)()
        return self.env[action['res_model']].browse(action['res_id']), calls

    def _select(self, wizard, name, *responses):
        line = wizard.line_ids.filtered(lambda line: line.name == name)
        if not responses:
            return line.action_select()
        with mock_neoship(make_response(json_data=LOGIN_OK), *responses):
            return line.action_select()

    def _wizard(self, action):
        return self.env[action['res_model']].browse(action['res_id'])

    def _choose_packeta(self, carrier_type_name):
        wizard, _calls = self._open('action_neoship_choose_shipper', SHIPPERS)
        action = self._select(wizard, 'Packeta', make_response(json_data=PACKETA_CARRIERS))
        self._select(self._wizard(action), carrier_type_name)

    def _schedules(self, carrier=None):
        return (
            self.env['neoship.closure.schedule']
            .with_context(active_test=False)
            .search([('carrier_id', '=', (carrier or self.carrier).id)])
        )

    def test_shipper_options_come_from_api(self):
        wizard, calls = self._open('action_neoship_choose_shipper', SHIPPERS)
        self.assertTrue(calls[-1]['url'].endswith('/shipper/active'))
        self.assertEqual(wizard.kind, const.OPTION_KIND_SHIPPER)
        self.assertEqual(sorted(wizard.line_ids.mapped('value')), [2, 3, 4])

    def test_pickup_points_come_from_delivery_types(self):
        wizard, _calls = self._open('action_neoship_choose_shipper', SHIPPERS)
        pickup_points = {line.code: line.supports_parcelshops for line in wizard.line_ids}
        self.assertEqual(pickup_points, {'SPS': True, 'Packeta': True, '123': False})

    def test_account_without_connected_carriers_is_reported(self):
        with (
            mock_neoship(make_response(json_data=LOGIN_OK), make_response(json_data=[])),
            self.assertRaisesRegex(UserError, 'No carriers are connected'),
        ):
            self.carrier.action_neoship_choose_shipper()

    def test_select_shipper_stores_it_on_delivery_method(self):
        wizard, _calls = self._open('action_neoship_choose_shipper', SHIPPERS)
        self._select(wizard, 'SPS')
        self.assertEqual(self.carrier.neoship_shipper_id, 2)
        self.assertEqual(self.carrier.neoship_shipper_code, 'SPS')
        self.assertEqual(self.carrier.neoship_shipper_name, 'SPS')
        self.assertFalse(self.carrier.neoship_has_carrier_type)

    def test_selecting_packeta_asks_for_home_delivery_carrier_first(self):
        wizard, _calls = self._open('action_neoship_choose_shipper', SHIPPERS)
        with mock_neoship(make_response(json_data=LOGIN_OK), make_response(json_data=PACKETA_CARRIERS)) as calls:
            action = wizard.line_ids.filtered(lambda line: line.name == 'Packeta').action_select()
        self.assertTrue(calls[-1]['url'].endswith('/carrier/available'))
        carrier_type_wizard = self._wizard(action)
        self.assertEqual(carrier_type_wizard.kind, const.OPTION_KIND_CARRIER_TYPE)
        self.assertFalse(self.carrier.neoship_shipper_id)
        carrier_type_wizard.invalidate_recordset(['line_ids'])
        self.assertEqual(carrier_type_wizard.line_ids.mapped('name'), ['CZ Zásilkovna domů HD', 'SK Packeta Home HD'])

        self._select(carrier_type_wizard, 'SK Packeta Home HD')
        self.assertEqual(self.carrier.neoship_shipper_id, 3)
        self.assertEqual(self.carrier.neoship_carrier_type, 131)
        self.assertEqual(self.carrier.neoship_carrier_type_name, 'SK Packeta Home HD')
        self.assertEqual(self.carrier.neoship_carrier_type_country_id, self.env.ref('base.sk'))

    def test_change_packeta_home_delivery_carrier(self):
        self._choose_packeta('SK Packeta Home HD')
        wizard, _calls = self._open('action_neoship_choose_carrier_type', PACKETA_CARRIERS)
        self._select(wizard, 'CZ Zásilkovna domů HD')
        self.assertEqual(self.carrier.neoship_shipper_id, 3)
        self.assertEqual(self.carrier.neoship_carrier_type, 106)
        self.assertEqual(self.carrier.neoship_carrier_type_country_id, self.env.ref('base.cz'))

    def test_packeta_carrier_countries_come_from_state_code(self):
        wizard, _calls = self._open('action_neoship_choose_carrier_type', PACKETA_CARRIERS)
        countries = {line.name: line.country_id for line in wizard.line_ids}
        self.assertEqual(countries['SK Packeta Home HD'], self.env.ref('base.sk'))
        self.assertEqual(countries['CZ Zásilkovna domů HD'], self.env.ref('base.cz'))

    def test_unknown_packeta_country_code_is_left_empty(self):
        carriers = [{**PACKETA_CARRIERS[0], 'packeta_id': 999, 'name': 'XX New Carrier HD', 'state_code': 'XX'}]
        self._choose_packeta('SK Packeta Home HD')
        wizard, _calls = self._open('action_neoship_choose_carrier_type', carriers)
        self._select(wizard, 'XX New Carrier HD')
        self.assertEqual(self.carrier.neoship_carrier_type, 999)
        self.assertFalse(self.carrier.neoship_carrier_type_country_id)

    def test_packeta_without_home_delivery_carrier_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.carrier._neoship_set_shipper(3, 'Packeta', 'Packeta')

    def test_switching_away_from_packeta_clears_carrier_type(self):
        self._choose_packeta('SK Packeta Home HD')
        wizard, _calls = self._open('action_neoship_choose_shipper', SHIPPERS)
        self._select(wizard, 'SPS')
        self.assertFalse(self.carrier.neoship_carrier_type)
        self.assertFalse(self.carrier.neoship_carrier_type_name)
        self.assertFalse(self.carrier.neoship_carrier_type_country_id)

    def test_switching_environment_clears_carrier(self):
        self._choose_packeta('SK Packeta Home HD')
        self.carrier.toggle_prod_environment()
        self.assertTrue(self.carrier.prod_environment)
        self.assertFalse(self.carrier.neoship_shipper_id)
        self.assertFalse(self.carrier.neoship_shipper_name)
        self.assertFalse(self.carrier.neoship_carrier_type)

    def test_writing_same_environment_keeps_carrier(self):
        self._choose_packeta('SK Packeta Home HD')
        self.carrier.write({'prod_environment': False})
        self.assertEqual(self.carrier.neoship_shipper_id, 3)

    def test_api_error_is_reported(self):
        with (
            mock_neoship(make_response(json_data=LOGIN_OK), make_response(500, {'message': 'Server error'})),
            self.assertRaisesRegex(UserError, 'Server error'),
        ):
            self.carrier.action_neoship_choose_shipper()

    def test_stock_manager_without_admin_rights_can_choose_options(self):
        manager = new_test_user(self.env, login='neoship_stock_manager', groups='stock.group_stock_manager')
        carrier = self.carrier.with_user(manager)
        wizard, _calls = self._open('action_neoship_choose_shipper', SHIPPERS, carrier)
        action = self._select(wizard.with_user(manager), 'Packeta', make_response(json_data=PACKETA_CARRIERS))
        self._select(self._wizard(action).with_user(manager), 'SK Packeta Home HD')
        self.assertEqual(self.carrier.neoship_shipper_id, 3)
        self.assertEqual(self.carrier.neoship_carrier_type, 131)

    def test_choosing_carrier_with_closure_creates_archived_schedule(self):
        wizard, _calls = self._open('action_neoship_choose_shipper', SHIPPERS)
        action = self._select(wizard, 'SPS')
        schedule = self._schedules()
        self.assertEqual(len(schedule), 1)
        self.assertFalse(schedule.active)
        self.assertFalse(schedule.cron_id.active)
        self.assertEqual(schedule.closure_time, const.CLOSURE_DEFAULT_TIME)
        self.assertEqual([schedule[day] for day in const.WEEKDAY_FIELDS], [True, True, True, True, True, False, False])
        self.assertEqual(action['tag'], 'display_notification')
        self.assertIn(self.carrier.name, action['params']['message'])
        self.assertEqual(action['params']['next'], {'type': 'ir.actions.act_window_close'})
        self.assertTrue(action['params']['message'].endswith('%s'))
        self.assertEqual(
            action['params']['links'][0]['url'],
            f'/odoo/action-delivery_neoship.action_neoship_closure_schedule/{schedule.id}',
        )
        self.assertEqual(self.carrier.neoship_closure_schedule_count, 1)

    def test_choosing_carrier_without_closure_creates_no_schedule(self):
        wizard, _calls = self._open('action_neoship_choose_shipper', SHIPPERS)
        action = self._select(wizard, '123kuriér')
        self.assertEqual(action, {'type': 'ir.actions.act_window_close'})
        self.assertFalse(self._schedules())

    def test_choosing_same_carrier_again_keeps_schedule_active(self):
        wizard, _calls = self._open('action_neoship_choose_shipper', SHIPPERS)
        self._select(wizard, 'SPS')
        self._schedules().active = True
        wizard, _calls = self._open('action_neoship_choose_shipper', SHIPPERS)
        action = self._select(wizard, 'SPS')
        self.assertEqual(action, {'type': 'ir.actions.act_window_close'})
        self.assertTrue(self._schedules().active)

    def test_account_carrier_with_schedule_gets_no_second_one(self):
        self._choose_packeta('SK Packeta Home HD')
        packeta_cz = self.carrier.copy({'name': 'Neoship Packeta CZ'})
        packeta_cz._neoship_set_shipper(False, False, False)
        wizard, _calls = self._open('action_neoship_choose_shipper', SHIPPERS, packeta_cz)
        action = self._select(wizard, 'Packeta', make_response(json_data=PACKETA_CARRIERS))
        self._select(self._wizard(action), 'CZ Zásilkovna domů HD')
        self.assertEqual(packeta_cz.neoship_shipper_id, 3)
        self.assertFalse(self._schedules(packeta_cz), 'The closure covers the whole account at Packeta.')

    def test_changing_carrier_archives_schedule(self):
        wizard, _calls = self._open('action_neoship_choose_shipper', SHIPPERS)
        self._select(wizard, 'SPS')
        schedule = self._schedules()
        schedule.active = True
        wizard, _calls = self._open('action_neoship_choose_shipper', SHIPPERS)
        self._select(wizard, '123kuriér')
        self.assertFalse(schedule.active)
        self.assertFalse(schedule.cron_id.active)

    def test_switching_environment_archives_schedule(self):
        wizard, _calls = self._open('action_neoship_choose_shipper', SHIPPERS)
        self._select(wizard, 'SPS')
        schedule = self._schedules()
        schedule.active = True
        self.carrier.toggle_prod_environment()
        self.assertFalse(schedule.active)

    def test_stock_manager_choice_creates_schedule(self):
        manager = new_test_user(self.env, login='neoship_stock_manager_2', groups='stock.group_stock_manager')
        carrier = self.carrier.with_user(manager)
        wizard, _calls = self._open('action_neoship_choose_shipper', SHIPPERS, carrier)
        action = self._select(wizard.with_user(manager), 'SPS')
        self.assertEqual(len(self._schedules()), 1)
        self.assertNotIn('links', action['params'], 'Only administrators can open closure schedules.')
        self.assertNotIn('%s', action['params']['message'])
        self.assertEqual(carrier.neoship_closure_schedule_count, 1)
