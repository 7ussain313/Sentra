from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    vehicle_ids = fields.One2many("carwash.vehicle", "owner_id", string="Vehicles")
    booking_ids = fields.One2many("carwash.booking", "customer_id", string="Car Wash Bookings")
