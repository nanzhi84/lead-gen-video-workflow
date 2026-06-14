"""G4/R6/F-#2 in-memory coverage: case profile fields, list counts, import brief.

These exercise the in-memory backend (CUTAGENT_STORAGE_BACKEND=memory, set by
tests/conftest.py) through the public API so the contract field names and the
service mappings are validated end-to-end. The SQLAlchemy path is covered by the
gated integration tests in tests/integration/test_sqlalchemy_cases.py and
test_sqlalchemy_case_learning.py.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.app import create_app
from packages.ai.prompts.registry import case_prompt_variables
from packages.core import contracts as c


def _login_admin(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@local.cutagent", "password": "local-admin"},
    )
    assert response.status_code == 200, response.text


PROFILE_PAYLOAD = {
    "name": "Profile Case",
    "industry": "retail",
    "product": "Widget",
    "target_audience": "operators",
    "description": "Seeded profile case.",
    "key_selling_points": ["fast", "cheap"],
    "ip_persona": "friendly expert",
    "brand_voice": "warm and direct",
    "strategy_tags": ["promo", "q3"],
    "brand_keywords": ["acme"],
    "competitor_names": ["globex"],
}


def test_create_case_round_trips_all_profile_fields() -> None:
    with TestClient(create_app()) as client:
        _login_admin(client)
        created = client.post("/api/cases", json=PROFILE_PAYLOAD)
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["key_selling_points"] == ["fast", "cheap"]
        assert body["ip_persona"] == "friendly expert"
        assert body["brand_voice"] == "warm and direct"
        assert body["strategy_tags"] == ["promo", "q3"]
        assert body["brand_keywords"] == ["acme"]
        assert body["competitor_names"] == ["globex"]
        assert body["industry"] == "retail"


def test_patch_case_updates_profile_fields() -> None:
    with TestClient(create_app()) as client:
        _login_admin(client)
        created = client.post("/api/cases", json={"name": "Patch Profile Case"})
        assert created.status_code == 201, created.text
        case_id = created.json()["id"]

        patched = client.patch(
            f"/api/cases/{case_id}",
            json={
                "industry": "education",
                "key_selling_points": ["x", "y"],
                "ip_persona": "mentor",
                "brand_voice": "calm",
                "strategy_tags": ["evergreen"],
                "brand_keywords": ["kw"],
                "competitor_names": ["rival"],
            },
        )
        assert patched.status_code == 200, patched.text
        body = patched.json()
        assert body["industry"] == "education"
        assert body["key_selling_points"] == ["x", "y"]
        assert body["ip_persona"] == "mentor"
        assert body["brand_voice"] == "calm"
        assert body["strategy_tags"] == ["evergreen"]
        assert body["brand_keywords"] == ["kw"]
        assert body["competitor_names"] == ["rival"]

        detail = client.get(f"/api/cases/{case_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["industry"] == "education"
        assert detail.json()["key_selling_points"] == ["x", "y"]


def test_list_cases_industry_filter_and_counts() -> None:
    with TestClient(create_app()) as client:
        _login_admin(client)
        created = client.post(
            "/api/cases",
            json={"name": "Filterable Case", "industry": "fintech"},
        )
        assert created.status_code == 201, created.text
        case_id = created.json()["id"]

        matched = client.get("/api/cases", params={"industry": "fintech"})
        assert matched.status_code == 200, matched.text
        assert any(item["id"] == case_id for item in matched.json()["items"])

        unmatched = client.get("/api/cases", params={"industry": "no-such-industry"})
        assert unmatched.status_code == 200, unmatched.text
        assert all(item["id"] != case_id for item in unmatched.json()["items"])

        # Every list item exposes the R6 count fields with safe defaults.
        for item in matched.json()["items"]:
            assert "material_count" in item
            assert "script_count" in item
            assert "voice_count" in item
            assert "quality_count" in item


def test_seeded_demo_case_reports_material_count_from_assets() -> None:
    # The seed creates 4 reusable media assets (portrait/broll/bgm/font) for
    # case_demo, so material_count must be 4 (R6 count semantics).
    with TestClient(create_app()) as client:
        _login_admin(client)
        listing = client.get("/api/cases", params={"search": "Demo", "limit": 200})
        assert listing.status_code == 200, listing.text
        demo = next(item for item in listing.json()["items"] if item["id"] == "case_demo")
        assert demo["material_count"] == 4
        assert demo["voice_count"] == 0  # seeded voice is a VoiceProfile, not a media asset
        assert demo["script_count"] == 0
        assert demo["quality_count"] == 0


def test_import_case_source_emits_real_brief_for_text_binding() -> None:
    with TestClient(create_app()) as client:
        _login_admin(client)
        binding = client.post(
            "/api/cases/case_demo/agent/source-bindings",
            json={
                "source_type": "text",
                "source_ref": "首屏先给具体成果。\n再讲清楚方法。\n最后给行动建议。",
                "title": "Audience note",
            },
        )
        assert binding.status_code == 201, binding.text
        binding_id = binding.json()["id"]

        imported = client.post(
            "/api/cases/case_demo/agent/import-source",
            json={"source_binding_id": binding_id},
        )
        assert imported.status_code == 202, imported.text
        run = imported.json()
        assert run["goal"] == "brief"
        run_id = run["id"]

        detail = client.get(f"/api/cases/case_demo/agent/runs/{run_id}")
        assert detail.status_code == 200, detail.text
        briefs = detail.json()["briefs"]
        assert briefs
        brief = briefs[-1]
        # F/#2: no longer the stub summary; real §32.4 fields are populated.
        assert brief["summary"] != "Imported source summary."
        assert brief["summary"]
        assert brief["topic"] == "Audience note"
        assert brief["key_insights"]
        assert brief["source_refs"]
        assert brief["generated_by_run_id"] == run_id


def test_case_prompt_variables_bridges_contract_to_template_vocabulary() -> None:
    case = c.CaseDetail(
        id="case_probe",
        name="Acme Co",
        product="Widget",
        industry="retail",
        target_audience="ops",
        description="desc",
        key_selling_points=["fast", "cheap"],
        ip_persona="friendly",
        brand_voice="warm",
        strategy_tags=["promo", "q3"],
        brand_keywords=["acme"],
        competitor_names=["globex"],
    )
    variables = case_prompt_variables(case)
    assert variables["case_name"] == "Acme Co"
    assert variables["product_name"] == "Widget"
    assert variables["industry"] == "retail"
    assert variables["target_audience"] == "ops"
    assert variables["ip_persona"] == "friendly"
    assert variables["brand_voice"] == "warm"
    # List fields are joined, not Python-list reprs.
    assert variables["key_selling_points"] == "fast, cheap"
    assert variables["tags"] == "promo, q3"
    assert variables["description"] == "desc"
    # brand_keywords / competitor_names have no template var today.
    assert "brand_keywords" not in variables
    assert "competitor_names" not in variables
