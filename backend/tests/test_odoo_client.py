import pytest
from datetime import date
from app.services.odoo_client import OdooClient


@pytest.mark.asyncio
async def test_odoo_client_test_connection():
    client = OdooClient()
    res = await client.test_connection()
    assert res["success"] is True
    assert res["mode"] in ("sandbox_mock", "live")


@pytest.mark.asyncio
async def test_odoo_client_partner():
    client = OdooClient()
    partner_id = await client.find_or_create_partner(
        name="Acme IoT Corp",
        email="billing@acmeiot.com",
        phone="+1-800-555-0100",
    )
    assert partner_id > 0

    # Repeating with same email returns same partner
    partner_id_2 = await client.find_or_create_partner(
        name="Acme IoT Corp",
        email="billing@acmeiot.com",
    )
    assert partner_id == partner_id_2


@pytest.mark.asyncio
async def test_odoo_client_invoice_workflow():
    client = OdooClient()
    partner_id = await client.find_or_create_partner(name="Test Partner")

    lines = [
        {"name": "Starter Cellular IoT Subscription", "quantity": 1.0, "unit_price": 19.00},
        {"name": "Cellular Data Overage (150 MB)", "quantity": 150.0, "unit_price": 0.05},
    ]

    inv = await client.create_customer_invoice(
        partner_id=partner_id,
        line_items=lines,
        invoice_date=date.today(),
        due_date=date.today(),
        ref="NIB-TEST-INV-1",
        auto_post=True,
    )

    assert inv["id"] is not None
    assert inv["amount_subtotal"] == 19.00 + (150 * 0.05)
    assert inv["state"] == "posted"
    assert inv["payment_state"] == "not_paid"

    # Fetch invoice
    fetched = await client.get_invoice(inv["id"])
    assert fetched["id"] == inv["id"]

    # Mark as paid
    paid = await client.mark_invoice_as_paid(inv["id"])
    assert paid["payment_state"] == "paid"

    # PDF rendering
    pdf_b64 = await client.get_invoice_pdf_base64(inv["id"])
    assert len(pdf_b64) > 20
