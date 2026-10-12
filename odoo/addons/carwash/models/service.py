from odoo import fields, models


class CarwashService(models.Model):
    _name = "carwash.service"
    _description = "Car Wash Service"
    _order = "name"

    name = fields.Char(required=True)
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id,
        required=True,
    )
    price = fields.Monetary(required=True, currency_field="currency_id")
    duration = fields.Integer(string="Duration (min)", required=True, default=30)
    active = fields.Boolean(default=True)
    booking_ids = fields.One2many("carwash.booking", "service_id", string="Bookings")

    _sql_constraints = [
        ("price_non_negative", "CHECK(price >= 0)", "The service price cannot be negative."),
        ("duration_positive", "CHECK(duration > 0)", "The duration must be greater than zero."),
    ]
