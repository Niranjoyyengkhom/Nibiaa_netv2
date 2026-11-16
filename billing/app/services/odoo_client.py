import asyncio
import base64
import os
import time
import logging
import xmlrpc.client
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nibiaanet.odoo")


class OdooClient:
    """
    Universal Odoo ERP Client using XML-RPC / JSON-RPC External API.
    Interacts with:
    - res.partner (Tenants / Customers)
    - product.product (IoT Plans, Quota Top-Ups, SIM Lines)
    - account.move & account.move.line (Customer Invoices)
    - ir.actions.report (Invoice PDF report rendering)

    Includes an in-memory Sandbox/Mock simulation for local offline development.
    """

    def __init__(
        self,
        url: Optional[str] = None,
        db: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: float = 15.0,
        sandbox_mode: Optional[bool] = None,
    ):
        self.url = (url or os.getenv("ODOO_URL") or "http://localhost:8069").rstrip("/")
        self.db = db or os.getenv("ODOO_DB") or "odoo"
        self.username = username or os.getenv("ODOO_USERNAME") or "admin"
        self.password = password or os.getenv("ODOO_PASSWORD") or os.getenv("ODOO_API_KEY") or ""
        self.timeout = timeout
        self._sandbox_mode = sandbox_mode

        self._uid: Optional[int] = None

        # In-memory mock storage
        self._mock_partners: Dict[int, Dict[str, Any]] = {
            1: {
                "id": 1,
                "name": "Nibiaa Demo Organization",
                "email": "demo@nibiaa.com",
                "phone": "+1-555-0199",
                "vat": "US998877665",
            }
        }
        self._mock_invoices: Dict[int, Dict[str, Any]] = {}
        self._mock_invoice_seq: int = 1000

    @property
    def is_configured(self) -> bool:
        return bool(self.url and self.db and self.username and self.password)

    @property
    def is_mock_mode(self) -> bool:
        if self._sandbox_mode is not None:
            return self._sandbox_mode
        forced_mock = os.getenv("ODOO_MOCK_MODE", "").lower() in ("true", "1", "yes")
        return forced_mock or not self.is_configured

    def _sync_authenticate(self) -> int:
        """Synchronously authenticates with Odoo via XML-RPC common proxy."""
        if self._uid:
            return self._uid

        common_url = f"{self.url}/xmlrpc/2/common"
        common = xmlrpc.client.ServerProxy(common_url, allow_none=True)
        uid = common.authenticate(self.db, self.username, self.password, {})
        if not uid:
            raise ConnectionError(
                f"Failed to authenticate with Odoo at {self.url} for user '{self.username}' on db '{self.db}'."
            )
        self._uid = uid
        return uid

    def _sync_execute_kw(self, model: str, method: str, *args, **kwargs) -> Any:
        """Synchronously invokes Odoo models.execute_kw."""
        uid = self._sync_authenticate()
        object_url = f"{self.url}/xmlrpc/2/object"
        models = xmlrpc.client.ServerProxy(object_url, allow_none=True)
        return models.execute_kw(self.db, uid, self.password, model, method, list(args), kwargs)

    async def execute_kw(self, model: str, method: str, *args, **kwargs) -> Any:
        """Asynchronously dispatches execution of Odoo XML-RPC call."""
        return await asyncio.to_thread(self._sync_execute_kw, model, method, *args, **kwargs)

    async def test_connection(self) -> Dict[str, Any]:
        """Tests connectivity and credentials with the Odoo server."""
        t0 = time.time()
        if self.is_mock_mode:
            return {
                "success": True,
                "mode": "sandbox_mock",
                "message": "Connected to Odoo Sandbox Simulator. Automated in-memory invoice generation active.",
                "latency_ms": round((time.time() - t0) * 1000, 2),
                "details": {
                    "url": self.url,
                    "db": self.db,
                    "username": self.username,
                    "note": "Set ODOO_URL, ODOO_DB, ODOO_USERNAME and ODOO_PASSWORD/ODOO_API_KEY for live Odoo ERP.",
                },
            }

        try:
            uid = await asyncio.to_thread(self._sync_authenticate)
            version = await asyncio.to_thread(
                lambda: xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common").version()
            )
            latency = round((time.time() - t0) * 1000, 2)
            return {
                "success": True,
                "mode": "live",
                "message": f"Successfully connected and authenticated to Odoo (UID: {uid}).",
                "latency_ms": latency,
                "details": {
                    "url": self.url,
                    "db": self.db,
                    "uid": uid,
                    "server_version": version.get("server_version", "unknown"),
                },
            }
        except Exception as e:
            return {
                "success": False,
                "mode": "live",
                "message": f"Connection to Odoo failed: {e}",
                "latency_ms": round((time.time() - t0) * 1000, 2),
                "details": {"error": str(e)},
            }

    async def find_or_create_partner(
        self,
        name: str,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        vat: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> int:
        """
        Finds an existing customer partner in Odoo or creates a new one.
        Model: res.partner
        """
        if self.is_mock_mode:
            for pid, partner in self._mock_partners.items():
                if email and partner.get("email") == email:
                    return pid
                if partner.get("name") == name:
                    return pid
            new_id = len(self._mock_partners) + 1
            self._mock_partners[new_id] = {
                "id": new_id,
                "name": name,
                "email": email,
                "phone": phone,
                "vat": vat,
            }
            return new_id

        # Live Odoo: Search by email or name
        domain = []
        if email:
            domain = [["email", "=ilike", email.strip()]]
        else:
            domain = [["name", "=ilike", name.strip()]]

        existing = await self.execute_kw("res.partner", "search_read", domain, ["id", "name", "email"])
        if existing and len(existing) > 0:
            return existing[0]["id"]

        # Create new res.partner
        vals = {
            "name": name,
            "customer_rank": 1,
            "comment": notes or "Created automatically by NibiaaNet IoT Platform",
        }
        if email:
            vals["email"] = email
        if phone:
            vals["phone"] = phone
        if vat:
            vals["vat"] = vat

        partner_id = await self.execute_kw("res.partner", "create", vals)
        return partner_id

    async def find_or_create_product(
        self,
        name: str,
        code: str,
        price: float = 0.0,
        product_type: str = "service",
    ) -> int:
        """
        Finds or creates a product in Odoo catalog.
        Model: product.product
        """
        if self.is_mock_mode:
            return 99 # Mock product ID

        existing = await self.execute_kw(
            "product.product",
            "search_read",
            [["default_code", "=", code]],
            ["id", "name", "list_price"],
        )
        if existing and len(existing) > 0:
            return existing[0]["id"]

        vals = {
            "name": name,
            "default_code": code,
            "type": product_type,
            "list_price": price,
            "sale_ok": True,
            "purchase_ok": False,
        }
        product_id = await self.execute_kw("product.product", "create", vals)
        return product_id

    async def create_customer_invoice(
        self,
        partner_id: int,
        line_items: List[Dict[str, Any]],
        invoice_date: Optional[date] = None,
        due_date: Optional[date] = None,
        ref: Optional[str] = None,
        notes: Optional[str] = None,
        currency_code: str = "USD",
        auto_post: bool = True,
    ) -> Dict[str, Any]:
        """
        Creates a customer invoice (out_invoice) in Odoo with specified line items.
        Model: account.move
        """
        inv_date_str = (invoice_date or date.today()).isoformat()
        due_date_str = (due_date or date.today()).isoformat()

        if self.is_mock_mode:
            self._mock_invoice_seq += 1
            inv_id = self._mock_invoice_seq
            inv_number = f"INV/{date.today().year}/{inv_id:05d}"

            subtotal = sum(item["quantity"] * item["unit_price"] for item in line_items)
            tax = round(subtotal * 0.10, 2)
            total = round(subtotal + tax, 2)

            invoice_record = {
                "id": inv_id,
                "name": inv_number,
                "partner_id": partner_id,
                "state": "posted" if auto_post else "draft",
                "payment_state": "not_paid",
                "amount_subtotal": subtotal,
                "amount_tax": tax,
                "amount_total": total,
                "amount_residual": total,
                "invoice_date": inv_date_str,
                "invoice_date_due": due_date_str,
                "ref": ref or f"NIBIAA-INV-{inv_id}",
                "line_items": line_items,
                "currency": currency_code,
            }
            self._mock_invoices[inv_id] = invoice_record
            return invoice_record

        # Prepare Odoo invoice line commands (tuple notation: (0, 0, dict))
        invoice_lines = []
        for line in line_items:
            line_vals = {
                "name": line.get("name", "IoT Subscription Service"),
                "quantity": float(line.get("quantity", 1.0)),
                "price_unit": float(line.get("unit_price", 0.0)),
            }
            if line.get("product_id"):
                line_vals["product_id"] = line["product_id"]
            invoice_lines.append((0, 0, line_vals))

        invoice_vals: Dict[str, Any] = {
            "partner_id": partner_id,
            "move_type": "out_invoice",
            "invoice_date": inv_date_str,
            "invoice_date_due": due_date_str,
            "ref": ref or f"NIBIAA-{int(time.time())}",
            "narration": notes or "Generated by NibiaaNet Billing Engine",
            "invoice_line_ids": invoice_lines,
        }

        # Create move
        invoice_id = await self.execute_kw("account.move", "create", invoice_vals)

        # Post / validate invoice
        if auto_post:
            try:
                await self.execute_kw("account.move", "action_post", [invoice_id])
            except Exception as pe:
                logger.warning(f"Could not automatically post Odoo invoice {invoice_id}: {pe}")

        # Read back generated invoice fields
        return await self.get_invoice(invoice_id)

    async def get_invoice(self, odoo_invoice_id: int) -> Dict[str, Any]:
        """
        Reads invoice state, name, amounts, and payment status from Odoo.
        Model: account.move
        """
        if self.is_mock_mode:
            if odoo_invoice_id in self._mock_invoices:
                return self._mock_invoices[odoo_invoice_id]
            # Return generic mock record if not found
            return {
                "id": odoo_invoice_id,
                "name": f"INV/{date.today().year}/{odoo_invoice_id:05d}",
                "state": "posted",
                "payment_state": "not_paid",
                "amount_total": 50.0,
                "amount_residual": 50.0,
            }

        fields = [
            "id",
            "name",
            "state",
            "payment_state",
            "amount_untaxed",
            "amount_tax",
            "amount_total",
            "amount_residual",
            "invoice_date",
            "invoice_date_due",
            "ref",
        ]
        records = await self.execute_kw("account.move", "read", [odoo_invoice_id], fields)
        if not records:
            raise ValueError(f"Odoo invoice ID {odoo_invoice_id} not found.")

        rec = records[0]
        return {
            "id": rec["id"],
            "name": rec.get("name"),
            "state": rec.get("state"),
            "payment_state": rec.get("payment_state", "not_paid"),
            "amount_subtotal": rec.get("amount_untaxed", 0.0),
            "amount_tax": rec.get("amount_tax", 0.0),
            "amount_total": rec.get("amount_total", 0.0),
            "amount_residual": rec.get("amount_residual", 0.0),
            "invoice_date": str(rec.get("invoice_date")),
            "invoice_date_due": str(rec.get("invoice_date_due")),
            "ref": rec.get("ref"),
        }

    async def mark_invoice_as_paid(
        self,
        odoo_invoice_id: int,
        payment_method: str = "manual",
    ) -> Dict[str, Any]:
        """
        Marks an invoice as paid (in mock mode or via Odoo payment register).
        """
        if self.is_mock_mode:
            if odoo_invoice_id in self._mock_invoices:
                self._mock_invoices[odoo_invoice_id]["payment_state"] = "paid"
                self._mock_invoices[odoo_invoice_id]["amount_residual"] = 0.0
                return self._mock_invoices[odoo_invoice_id]
            return {
                "id": odoo_invoice_id,
                "payment_state": "paid",
                "amount_residual": 0.0,
            }

        # For live Odoo: In Odoo 14-18, payments are typically registered via
        # account.payment.register wizard.
        try:
            wizard_vals = {
                "payment_date": date.today().isoformat(),
            }
            context = {
                "active_model": "account.move",
                "active_ids": [odoo_invoice_id],
            }
            # Execute payment registration wizard
            wizard_id = await self.execute_kw(
                "account.payment.register",
                "create",
                wizard_vals,
                {"context": context},
            )
            await self.execute_kw(
                "account.payment.register",
                "action_create_payments",
                [wizard_id],
                {"context": context},
            )
        except Exception as e:
            logger.warning(f"Could not trigger account.payment.register wizard on Odoo: {e}")

        return await self.get_invoice(odoo_invoice_id)

    async def get_invoice_pdf_base64(self, odoo_invoice_id: int) -> str:
        """
        Retrieves or renders invoice PDF as base64 string.
        """
        if self.is_mock_mode:
            # Return minimal valid base64 PDF header for testing
            mock_pdf = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj 3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>>>endobj\nxref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000052 00000 n \n0000000115 00000 n \ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n200\n%%EOF"
            return base64.b64encode(mock_pdf).decode("ascii")

        # Live Odoo: Use ir.actions.report
        report_service = f"{self.url}/xmlrpc/2/report"
        uid = self._sync_authenticate()
        report = xmlrpc.client.ServerProxy(report_service, allow_none=True)

        res = await asyncio.to_thread(
            report.render_pdf,
            self.db,
            uid,
            self.password,
            "account.report_invoice",
            [odoo_invoice_id],
        )
        if isinstance(res, (tuple, list)) and len(res) > 0:
            pdf_bytes = res[0]
            return base64.b64encode(pdf_bytes).decode("ascii")
        raise RuntimeError("Failed to render invoice PDF on Odoo server.")


# Shared singleton instance
odoo_client = OdooClient()
