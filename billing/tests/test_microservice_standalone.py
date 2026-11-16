import os
import sys
import unittest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app
from app.dependencies.auth import get_current_user, AuthUser

class TestBillingMicroservice(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_01_health_endpoint(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("status"), "ok")
        self.assertEqual(data.get("service"), "billing-microservice")
        self.assertEqual(data.get("port"), 3004)

    def test_02_driver_catalog(self):
        admin_user = AuthUser(id=1, email="admin@nibiaa.com", role="admin", tenant_id=None)
        app.dependency_overrides[get_current_user] = lambda: admin_user

        try:
            response = self.client.get("/network/drivers")
            self.assertEqual(response.status_code, 200)
            drivers = response.json()
            self.assertIsInstance(drivers, list)
            driver_types = [d["driver_type"] for d in drivers]
            self.assertIn("1nce", driver_types)
            self.assertIn("monogoto", driver_types)
            self.assertIn("emnify", driver_types)
            self.assertIn("twilio", driver_types)
            self.assertIn("generic_rest", driver_types)
        finally:
            app.dependency_overrides.clear()

    def test_03_billing_plans_list(self):
        admin_user = AuthUser(id=1, email="admin@nibiaa.com", role="admin", tenant_id=None)
        app.dependency_overrides[get_current_user] = lambda: admin_user

        try:
            response = self.client.get("/billing/plans")
            self.assertEqual(response.status_code, 200)
            plans = response.json()
            self.assertIsInstance(plans, list)
            self.assertGreaterEqual(len(plans), 1)
            p = plans[0]
            self.assertEqual(p.get("pricing_model"), "cost_plus_percentage")
            self.assertIn("markup_percentage", p)
        finally:
            app.dependency_overrides.clear()

    def test_04_billing_usage_admin_summary(self):
        admin_user = AuthUser(id=1, email="admin@nibiaa.com", role="admin", tenant_id=None)
        app.dependency_overrides[get_current_user] = lambda: admin_user

        try:
            response = self.client.get("/billing/usage")
            self.assertEqual(response.status_code, 200)
            summary = response.json()
            self.assertIn("total_active_sims", summary)
            self.assertIn("total_data_used_mb", summary)
            self.assertIn("provider_billed_cost", summary)
            self.assertIn("markup_amount", summary)
        finally:
            app.dependency_overrides.clear()

    def test_05_network_providers_list(self):
        admin_user = AuthUser(id=1, email="admin@nibiaa.com", role="admin", tenant_id=None)
        app.dependency_overrides[get_current_user] = lambda: admin_user

        try:
            response = self.client.get("/network/providers")
            self.assertEqual(response.status_code, 200)
            providers = response.json()
            self.assertIsInstance(providers, list)
            self.assertGreaterEqual(len(providers), 1)
            prov = providers[0]
            self.assertIn("markup_percentage", prov)
            self.assertIn("cost_per_mb", prov)
            self.assertIn("cost_per_sim", prov)
            self.assertIn("effective_customer_mb_rate", prov)
        finally:
            app.dependency_overrides.clear()

    def test_06_update_admin_markup(self):
        admin_user = AuthUser(id=1, email="admin@nibiaa.com", role="admin", tenant_id=None)
        app.dependency_overrides[get_current_user] = lambda: admin_user

        try:
            response = self.client.post("/billing/markup", json={"markup_percentage": 25.0})
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data.get("status"), "success")
            self.assertEqual(data.get("markup_percentage"), 25.0)
            self.assertEqual(data.get("has_fixed_amount"), False)
        finally:
            app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()
