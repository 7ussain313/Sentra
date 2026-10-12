from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    vehicle_ids = fields.One2many("carwash.vehicle", "owner_id", string="Vehicles")
    booking_ids = fields.One2many("carwash.booking", "customer_id", string="Car Wash Bookings")
    total_revenue = fields.Monetary(
        compute="_compute_total_revenue",
        currency_field="currency_id",
        help="Sum of posted car wash invoices for this customer.",
    )

    @api.depends("booking_ids.invoice_id.amount_total", "booking_ids.invoice_id.state")
    def _compute_total_revenue(self):
        for partner in self:
            invoices = partner.sudo().booking_ids.invoice_id.filtered(
                lambda m: m.state == "posted" and m.move_type == "out_invoice"
            )
            partner.total_revenue = sum(invoices.mapped("amount_total"))
