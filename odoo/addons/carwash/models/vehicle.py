import re

from odoo import api, fields, models


def normalize_plate(value):
    return re.sub(r"\s+", "", value or "").upper()


class CarwashVehicle(models.Model):
    _name = "carwash.vehicle"
    _description = "Car Wash Vehicle"
    _rec_name = "plate_number"
    _order = "plate_number"

    plate_number = fields.Char(required=True, index=True, copy=False)
    make = fields.Char()
    model = fields.Char()
    owner_id = fields.Many2one("res.partner", string="Owner", required=True, ondelete="restrict")
    booking_ids = fields.One2many("carwash.booking", "vehicle_id", string="Bookings")
    booking_count = fields.Integer(compute="_compute_booking_count")

    _sql_constraints = [
        ("plate_number_unique", "UNIQUE(plate_number)", "This plate number is already registered."),
    ]

    @api.depends("booking_ids")
    def _compute_booking_count(self):
        for vehicle in self:
            vehicle.booking_count = len(vehicle.booking_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("plate_number"):
                vals["plate_number"] = normalize_plate(vals["plate_number"])
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("plate_number"):
            vals["plate_number"] = normalize_plate(vals["plate_number"])
        return super().write(vals)
