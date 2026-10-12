from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class CarwashBooking(models.Model):
    _name = "carwash.booking"
    _description = "Car Wash Booking"
    _inherit = ["mail.thread"]
    _order = "scheduled_date desc, id desc"

    name = fields.Char(string="Reference", readonly=True, copy=False, default="New")
    customer_id = fields.Many2one(
        "res.partner", string="Customer", required=True, ondelete="restrict", tracking=True
    )
    vehicle_id = fields.Many2one(
        "carwash.vehicle",
        string="Vehicle",
        required=True,
        ondelete="restrict",
        domain="[('owner_id', '=', customer_id)]",
        tracking=True,
    )
    service_id = fields.Many2one(
        "carwash.service", string="Service", required=True, ondelete="restrict", tracking=True
    )
    scheduled_date = fields.Datetime(required=True, tracking=True)
    currency_id = fields.Many2one(
        "res.currency", related="service_id.currency_id", store=True, readonly=True
    )
    # Computed from the service, stored so later service price changes do not
    # alter existing bookings; editable so a Manager can override it.
    price = fields.Monetary(
        compute="_compute_price",
        store=True,
        readonly=False,
        precompute=True,
        currency_field="currency_id",
        tracking=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("confirmed", "Confirmed"),
            ("in_progress", "In Progress"),
            ("done", "Done"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
        required=True,
        copy=False,
        tracking=True,
    )
    invoice_id = fields.Many2one("account.move", string="Invoice", readonly=True, copy=False)

    @api.depends("service_id")
    def _compute_price(self):
        for booking in self:
            if booking.service_id:
                booking.price = booking.service_id.price

    @api.onchange("customer_id")
    def _onchange_customer_id(self):
        if self.vehicle_id and self.vehicle_id.owner_id != self.customer_id:
            self.vehicle_id = False

    @api.constrains("customer_id", "vehicle_id")
    def _check_vehicle_owner(self):
        for booking in self:
            if booking.vehicle_id.owner_id != booking.customer_id:
                raise ValidationError(
                    _("Vehicle %(plate)s does not belong to customer %(customer)s.",
                      plate=booking.vehicle_id.plate_number,
                      customer=booking.customer_id.display_name)
                )

    @api.model_create_multi
    def create(self, vals_list):
        now = fields.Datetime.now()
        for vals in vals_list:
            scheduled = vals.get("scheduled_date")
            if scheduled and fields.Datetime.to_datetime(scheduled) < now:
                raise ValidationError(_("The scheduled date cannot be in the past."))
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("carwash.booking") or "New"
        return super().create(vals_list)
