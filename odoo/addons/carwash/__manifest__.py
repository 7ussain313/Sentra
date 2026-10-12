{
    "name": "Car Wash",
    "version": "17.0.1.0.0",
    "summary": "Car wash bookings, vehicles and services integrated with Odoo invoicing",
    "category": "Services",
    "license": "LGPL-3",
    "depends": ["base", "mail", "sale", "account"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/booking_views.xml",
        "views/service_vehicle_views.xml",
        "views/menus.xml",
        "report/booking_receipt.xml",
    ],
    "installable": True,
    "application": True,
}
