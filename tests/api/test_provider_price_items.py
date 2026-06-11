from fastapi.testclient import TestClient

from apps.api.app import create_app


def test_price_catalog_items_are_readable_after_upsert():
    with TestClient(create_app()) as client:
        login = client.post(
            "/api/auth/login",
            json={"email": "admin@local.cutagent", "password": "local-admin"},
        )
        assert login.status_code == 200, login.text
        created = client.post(
            "/api/providers/price-catalogs",
            json={
                "catalog": {
                    "id": "price_catalog_api_items",
                    "provider_id": "sandbox",
                    "status": "draft",
                    "currency": "CNY",
                },
                "items": [
                    {
                        "id": "price_item_api_items",
                        "catalog_id": "price_catalog_api_items",
                        "provider_id": "sandbox",
                        "model_id": "local-model",
                        "capability_id": "text.generate",
                        "unit": "call",
                        "unit_price": {"currency": "CNY", "amount": 0.5},
                    }
                ],
            },
        )
        assert created.status_code == 201, created.text

        listed = client.get("/api/providers/price-catalogs/price_catalog_api_items/items")
        assert listed.status_code == 200, listed.text
        assert listed.json()["items"][0]["id"] == "price_item_api_items"
