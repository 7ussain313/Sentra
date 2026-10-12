from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


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
        "res.currency",
        related="service_id.currency_id",
        store=True,
        precompute=True,
        readonly=True,
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

    # ------------------------------------------------------------------
    # Create / write guards
    # ------------------------------------------------------------------
    @api.model
    def _is_manager(self):
        return self.env.su or self.env.user.has_group("carwash.group_manager")

    @api.model_create_multi
    def create(self, vals_list):
        now = fields.Datetime.now()
        is_manager = self._is_manager()
        for vals in vals_list:
            if vals.get("state", "draft") != "draft":
                raise UserError(_("A booking can only be created in the Draft state."))
            if "price" in vals and not is_manager:
                raise AccessError(_("Only a Manager can set the price manually."))
            scheduled = vals.get("scheduled_date")
            if scheduled and fields.Datetime.to_datetime(scheduled) < now:
                raise ValidationError(_("The scheduled date cannot be in the past."))
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("carwash.booking") or "New"
        return super().create(vals_list)

    def write(self, vals):
        if "state" in vals and not self.env.context.get("carwash_transition"):
            raise UserError(_("The state can only be changed with the workflow buttons."))
        if "price" in vals and not self._is_manager():
            raise AccessError(_("Only a Manager can override the price."))
        return super().write(vals)

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------
    def _transition(self, allowed_from, target):
        states = dict(self._fields["state"].selection)
        for booking in self:
            if booking.state not in allowed_from:
                raise UserError(
                    _("Booking %(name)s is %(state)s and cannot move to %(target)s.",
                      name=booking.name, state=states[booking.state], target=states[target])
                )
        self.with_context(carwash_transition=True).write({"state": target})

    def action_confirm(self):
        self._transition({"draft"}, "confirmed")

    def action_start(self):
        self._transition({"confirmed"}, "in_progress")

    def action_done(self):
        self._transition({"in_progress"}, "done")
        for booking in self:
            booking._create_invoice()

    def action_cancel(self):
        if not self._is_manager():
            raise AccessError(_("Only a Manager can cancel a booking."))
        self._transition({"draft", "confirmed", "in_progress"}, "cancelled")

    # ------------------------------------------------------------------
    # Invoicing
    # ------------------------------------------------------------------
    def _create_invoice(self):
        """Create and post the customer invoice once; never a second one."""
        self.ensure_one()
        if self.invoice_id:
            return self.invoice_id
        # Staff have no accounting rights; invoicing is part of the workflow.
        invoice = self.env["account.move"].sudo().create({
            "move_type": "out_invoice",
            "partner_id": self.customer_id.id,
            "invoice_date": fields.Date.context_today(self),
            "currency_id": (self.currency_id or self.service_id.currency_id).id,
            "invoice_origin": self.name,
            "invoice_line_ids": [(0, 0, {
                "name": "%s - %s" % (self.service_id.name, self.vehicle_id.plate_number),
                "quantity": 1,
                "price_unit": self.price,
            })],
        })
        invoice.action_post()
        self.with_context(carwash_transition=True).sudo().write({"invoice_id": invoice.id})
        # Posted as OdooBot so the workflow never depends on the user having an email.
        self.message_post(
            body=_("Invoice %s created.", invoice.name),
            author_id=self.env.ref("base.partner_root").id,
        )
        return invoice
