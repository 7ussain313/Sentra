from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger


class CarwashCommon(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        group = lambda x: env.ref("carwash.%s" % x)
        cls.staff = env["res.users"].create({
            "name": "Staff", "login": "cw_staff",
            "groups_id": [(6, 0, [group("group_staff").id])]})
        cls.manager = env["res.users"].create({
            "name": "Manager", "login": "cw_manager",
            "groups_id": [(6, 0, [group("group_manager").id])]})
        cls.agent = env["res.users"].create({
            "name": "Agent", "login": "cw_agent",
            "groups_id": [(6, 0, [group("group_agent_readonly").id])]})
        cls.customer = env["res.partner"].create({"name": "Test Customer"})
        cls.other = env["res.partner"].create({"name": "Other Customer"})
        cls.service = env["carwash.service"].create({"name": "Test Wash", "price": 25.0, "duration": 30})
        cls.vehicle = env["carwash.vehicle"].create({"plate_number": "tst 123", "owner_id": cls.customer.id})
        cls.future = fields.Datetime.now() + timedelta(days=1)

    def new_booking(self, user=None, **kw):
        vals = {"customer_id": self.customer.id, "vehicle_id": self.vehicle.id,
                "service_id": self.service.id, "scheduled_date": self.future}
        vals.update(kw)
        return self.env["carwash.booking"].with_user(user or self.manager).create(vals)


@tagged("post_install", "-at_install", "carwash")
class TestStateMachine(CarwashCommon):
    def test_full_happy_path(self):
        b = self.new_booking(self.staff)
        self.assertEqual(b.state, "draft")
        b.with_user(self.staff).action_confirm()
        self.assertEqual(b.state, "confirmed")
        b.with_user(self.staff).action_start()
        self.assertEqual(b.state, "in_progress")
        b.with_user(self.staff).action_done()
        self.assertEqual(b.state, "done")

    def test_invalid_transitions_raise(self):
        b = self.new_booking()
        for action in ("action_start", "action_done"):
            with self.assertRaises(UserError):
                getattr(b, action)()
        b.action_confirm()
        with self.assertRaises(UserError):
            b.action_confirm()
        with self.assertRaises(UserError):
            b.action_done()          # cannot skip in_progress
        self.assertEqual(b.state, "confirmed")

    def test_terminal_states(self):
        done = self.new_booking()
        done.action_confirm(); done.action_start(); done.action_done()
        for action in ("action_confirm", "action_start", "action_done", "action_cancel"):
            with self.assertRaises(UserError):
                getattr(done, action)()
        cancelled = self.new_booking()
        cancelled.action_cancel()
        self.assertEqual(cancelled.state, "cancelled")
        with self.assertRaises(UserError):
            cancelled.action_confirm()

    def test_cancel_from_every_open_state(self):
        for steps in ([], ["action_confirm"], ["action_confirm", "action_start"]):
            b = self.new_booking()
            for s in steps:
                getattr(b, s)()
            b.with_user(self.manager).action_cancel()
            self.assertEqual(b.state, "cancelled")

    def test_state_cannot_be_written_directly(self):
        b = self.new_booking()
        with self.assertRaises(UserError):
            b.write({"state": "done"})
        with self.assertRaises(UserError):
            self.env["carwash.booking"].create({
                "customer_id": self.customer.id, "vehicle_id": self.vehicle.id,
                "service_id": self.service.id, "scheduled_date": self.future, "state": "done"})

    def test_transitions_are_logged_in_chatter(self):
        b = self.new_booking()
        b.action_confirm()
        self.env.cr.precommit.run()
        self.assertTrue(b.message_ids, "creation/transition messages expected")


@tagged("post_install", "-at_install", "carwash")
class TestInvoicing(CarwashCommon):
    def _complete(self, booking):
        booking.action_confirm(); booking.action_start(); booking.action_done()

    def test_invoice_created_posted_and_linked(self):
        b = self.new_booking(self.staff)
        self._complete(b.with_user(self.staff))
        inv = b.invoice_id
        self.assertTrue(inv)
        self.assertEqual(inv.move_type, "out_invoice")
        self.assertEqual(inv.state, "posted")
        self.assertEqual(inv.partner_id, self.customer)
        self.assertEqual(len(inv.invoice_line_ids), 1)
        self.assertAlmostEqual(inv.amount_total, 25.0)
        self.assertEqual(inv.invoice_origin, b.name)

    def test_invoice_uses_overridden_price(self):
        b = self.new_booking(self.manager, price=40.0)
        self._complete(b)
        self.assertAlmostEqual(b.invoice_id.amount_total, 40.0)

    def test_service_price_change_does_not_affect_existing_booking(self):
        b = self.new_booking()
        self.service.write({"price": 99.0})
        self.assertAlmostEqual(b.price, 25.0)
        self._complete(b)
        self.assertAlmostEqual(b.invoice_id.amount_total, 25.0)

    def test_never_a_second_invoice(self):
        b = self.new_booking()
        self._complete(b)
        first = b.invoice_id
        self.assertEqual(b._create_invoice(), first)
        with self.assertRaises(UserError):
            b.action_done()
        count = self.env["account.move"].search_count([("invoice_origin", "=", b.name)])
        self.assertEqual(count, 1)

    def test_invoice_failure_keeps_booking_in_its_state(self):
        b = self.new_booking()
        b.action_confirm(); b.action_start()
        with patch("odoo.addons.account.models.account_move.AccountMove.action_post",
                   side_effect=UserError("boom")):
            with self.assertRaises(UserError):
                with self.env.cr.savepoint(), mute_logger("odoo.sql_db"):
                    b.action_done()
        b.invalidate_recordset()
        self.assertEqual(b.state, "in_progress")
        self.assertFalse(b.invoice_id)

    def test_customer_total_revenue_and_vehicle_booking_count(self):
        self.assertEqual(self.customer.total_revenue, 0.0)
        b1, b2 = self.new_booking(), self.new_booking()
        self._complete(b1)
        self.assertAlmostEqual(self.customer.total_revenue, 25.0)
        self._complete(b2)
        self.assertAlmostEqual(self.customer.total_revenue, 50.0)
        self.assertEqual(self.vehicle.booking_count, 2)

    def test_staff_without_accounting_rights_can_complete_booking(self):
        self.assertFalse(self.staff.has_group("account.group_account_invoice"))
        b = self.new_booking(self.staff)
        self._complete(b.with_user(self.staff))
        self.assertEqual(b.state, "done")


@tagged("post_install", "-at_install", "carwash")
class TestAccessRights(CarwashCommon):
    def test_staff_cannot_cancel(self):
        b = self.new_booking(self.staff)
        with self.assertRaises(AccessError):
            b.with_user(self.staff).action_cancel()

    def test_staff_cannot_override_price(self):
        b = self.new_booking(self.staff)
        with self.assertRaises(AccessError):
            b.with_user(self.staff).write({"price": 1.0})
        with self.assertRaises(AccessError):
            self.new_booking(self.staff, price=1.0)

    def test_manager_can_override_price_and_cancel(self):
        b = self.new_booking(self.manager)
        b.with_user(self.manager).write({"price": 12.0})
        self.assertAlmostEqual(b.price, 12.0)
        b.with_user(self.manager).action_cancel()
        self.assertEqual(b.state, "cancelled")

    def test_staff_cannot_delete_or_edit_services(self):
        b = self.new_booking(self.staff)
        with self.assertRaises(AccessError):
            b.with_user(self.staff).unlink()
        with self.assertRaises(AccessError):
            self.service.with_user(self.staff).write({"price": 1.0})
        with self.assertRaises(AccessError):
            self.service.with_user(self.staff).unlink()

    def test_staff_can_create_services_vehicles_and_bookings(self):
        self.env["carwash.service"].with_user(self.staff).create({"name": "S2", "price": 5, "duration": 5})
        self.env["carwash.vehicle"].with_user(self.staff).create(
            {"plate_number": "STF1", "owner_id": self.customer.id})
        self.assertTrue(self.new_booking(self.staff))

    def test_manager_can_delete(self):
        b = self.new_booking(self.manager)
        b.with_user(self.manager).unlink()
        self.assertFalse(b.exists())

    def test_agent_user_is_strictly_read_only(self):
        b = self.new_booking()
        ba = b.with_user(self.agent)
        self.assertEqual(ba.name, b.name)                                    # can read
        self.assertTrue(self.env["carwash.service"].with_user(self.agent).search([]))
        with self.assertRaises(AccessError):
            ba.write({"price": 1.0})
        with self.assertRaises(AccessError):
            self.env["carwash.booking"].with_user(self.agent).create({
                "customer_id": self.customer.id, "vehicle_id": self.vehicle.id,
                "service_id": self.service.id, "scheduled_date": self.future})
        with self.assertRaises(AccessError):
            ba.unlink()
        with self.assertRaises(AccessError):
            self.service.with_user(self.agent).write({"price": 1.0})
        with self.assertRaises(AccessError):
            self.env["res.partner"].with_user(self.agent).create({"name": "x"}) if False else \
                self.customer.with_user(self.agent).unlink()

    def test_manager_implies_staff(self):
        self.assertTrue(self.manager.has_group("carwash.group_staff"))
        self.assertFalse(self.staff.has_group("carwash.group_manager"))


@tagged("post_install", "-at_install", "carwash")
class TestConstraints(CarwashCommon):
    def test_plate_normalized_and_unique(self):
        self.assertEqual(self.vehicle.plate_number, "TST123")
        with self.assertRaises(Exception), mute_logger("odoo.sql_db"):
            with self.env.cr.savepoint():
                self.env["carwash.vehicle"].create({"plate_number": "t s t1 23", "owner_id": self.other.id})

    def test_past_date_rejected_on_create(self):
        with self.assertRaises(ValidationError):
            self.new_booking(scheduled_date=fields.Datetime.now() - timedelta(hours=1))

    def test_vehicle_must_belong_to_customer(self):
        with self.assertRaises(ValidationError):
            self.new_booking(customer_id=self.other.id)

    def test_service_values_validated(self):
        for vals in ({"price": -1, "duration": 10}, {"price": 5, "duration": 0}):
            with self.assertRaises(Exception), mute_logger("odoo.sql_db"):
                with self.env.cr.savepoint():
                    self.env["carwash.service"].create(dict(vals, name="bad"))

    def test_reference_sequence_and_relationships(self):
        b1, b2 = self.new_booking(), self.new_booking()
        self.assertTrue(b1.name.startswith("CW/"))
        self.assertNotEqual(b1.name, b2.name)
        self.assertIn(b1, self.customer.booking_ids)
        self.assertIn(b1, self.vehicle.booking_ids)
        self.assertIn(b1, self.service.booking_ids)
        self.assertIn(self.vehicle, self.customer.vehicle_ids)
