"""VantageLife 2.0 Backend API Tests"""
import os
import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://vantage-exec-build.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


# ---------- Session tokens cache ----------
@pytest.fixture(scope="module")
def tokens():
    out = {}
    for lvl in ["level_1", "level_2", "level_3", "level_4"]:
        r = requests.post(f"{API}/auth/demo-login", json={"level": lvl}, timeout=15)
        assert r.status_code == 200, f"demo-login {lvl} failed: {r.status_code} {r.text}"
        data = r.json()
        assert "session_token" in data and "user" in data
        assert data["user"]["role"] == lvl
        out[lvl] = data["session_token"]
    return out


def H(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------- AUTH ----------
class TestAuth:
    def test_demo_login_invalid(self):
        r = requests.post(f"{API}/auth/demo-login", json={"level": "level_99"}, timeout=15)
        assert r.status_code == 400

    def test_auth_me(self, tokens):
        for lvl, tok in tokens.items():
            r = requests.get(f"{API}/auth/me", headers=H(tok), timeout=15)
            assert r.status_code == 200, f"auth/me {lvl} -> {r.status_code}"
            body = r.json()
            assert body["user"]["role"] == lvl
            assert "role_label" in body

    def test_auth_me_unauthenticated(self):
        r = requests.get(f"{API}/auth/me", timeout=15)
        assert r.status_code == 401

    def test_logout_invalidates(self):
        r = requests.post(f"{API}/auth/demo-login", json={"level": "level_1"}, timeout=15)
        tok = r.json()["session_token"]
        assert requests.get(f"{API}/auth/me", headers=H(tok)).status_code == 200
        assert requests.post(f"{API}/auth/logout", headers=H(tok)).status_code == 200
        assert requests.get(f"{API}/auth/me", headers=H(tok)).status_code == 401


# ---------- DASHBOARD ----------
class TestDashboard:
    def test_summary_rbac_full_agency(self, tokens):
        r = requests.get(f"{API}/dashboard/summary", headers=H(tokens["level_4"]), timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert body["is_full_agency"] is True
        assert "total_alp" in body and "gate" in body and "delta_pct_vs_yesterday" in body

    def test_summary_rbac_scoped(self, tokens):
        for lvl in ["level_1", "level_2", "level_3"]:
            r = requests.get(f"{API}/dashboard/summary", headers=H(tokens[lvl]), timeout=15)
            assert r.status_code == 200
            body = r.json()
            assert body["is_full_agency"] is False, f"{lvl} should NOT be full agency"

    def test_ticker(self, tokens):
        r = requests.get(f"{API}/dashboard/ticker", headers=H(tokens["level_4"]), timeout=15)
        assert r.status_code == 200
        items = r.json().get("items", [])
        assert isinstance(items, list)
        assert len(items) <= 50
        if items:
            it = items[0]
            for k in ["agent_name", "alp", "market", "reps", "ts"]:
                assert k in it

    def test_platinum_wall(self, tokens):
        r = requests.get(f"{API}/dashboard/platinum-wall", headers=H(tokens["level_4"]), timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert "vets" in body and "rookies" in body
        assert isinstance(body["vets"], list) and isinstance(body["rookies"], list)
        assert len(body["vets"]) <= 3 and len(body["rookies"]) <= 3

    def test_offices_5_rows(self, tokens):
        r = requests.get(f"{API}/dashboard/offices", headers=H(tokens["level_4"]), timeout=15)
        assert r.status_code == 200
        offices = r.json()["offices"]
        names = [o["office"] for o in offices]
        assert set(names) == {"MCM", "AMP", "Dearborn", "Heritage", "Siren"}
        for o in offices:
            for k in ["alp", "sales", "avg_deal"]:
                assert k in o


# ---------- TEAM (RBAC 403 for level_1) ----------
class TestTeam:
    def test_team_forbidden_level_1(self, tokens):
        r = requests.get(f"{API}/team", headers=H(tokens["level_1"]), timeout=15)
        assert r.status_code == 403

    def test_team_ok_level_2_plus(self, tokens):
        for lvl in ["level_2", "level_3", "level_4"]:
            r = requests.get(f"{API}/team", headers=H(tokens[lvl]), timeout=15)
            assert r.status_code == 200, f"team {lvl} -> {r.status_code}"
            body = r.json()
            assert "team" in body and isinstance(body["team"], list)


# ---------- PULSE ----------
class TestPulse:
    def test_pulse_submit_and_today(self, tokens):
        payload = {"sets": 5, "sits": 3, "sales": 2, "ots_sits": 1, "ots_sales": 1,
                   "n1": 1, "refs_obtained": 2, "ref_sits": 1, "ref_sales": 0, "gross_alp": 2500.0}
        r = requests.post(f"{API}/pulse", headers=H(tokens["level_1"]), json=payload, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True and "entry" in data
        # verify today endpoint
        r2 = requests.get(f"{API}/pulse/me/today", headers=H(tokens["level_1"]), timeout=15)
        assert r2.status_code == 200
        assert r2.json()["totals"]["sales"] >= 2

    def test_pulse_streak(self, tokens):
        r = requests.get(f"{API}/pulse/me/streak", headers=H(tokens["level_1"]), timeout=15)
        assert r.status_code == 200
        assert "streak" in r.json()


# ---------- MANAGER ERASER ----------
class TestManager:
    def test_audit_forbidden_for_non_level_4(self, tokens):
        for lvl in ["level_1", "level_2", "level_3"]:
            r = requests.get(f"{API}/manager/audit", headers=H(tokens[lvl]), timeout=15)
            assert r.status_code == 403

    def test_audit_level_4_ok(self, tokens):
        r = requests.get(f"{API}/manager/audit", headers=H(tokens["level_4"]), timeout=15)
        assert r.status_code == 200
        assert "items" in r.json()

    def test_erase_requires_level_4(self, tokens):
        # Pick any agent_id from team
        tm = requests.get(f"{API}/team", headers=H(tokens["level_4"]), timeout=15).json()["team"]
        assert len(tm) > 0
        aid = tm[0]["agent_id"]
        sd = tm[0].get("sales_day") or None
        sd_r = requests.get(f"{API}/dashboard/summary", headers=H(tokens["level_4"])).json()["sales_day"]
        payload = {"agent_id": aid, "sales_day": sd_r, "new_alp": 1000.0, "reason": "short"}
        r = requests.post(f"{API}/manager/erase", headers=H(tokens["level_3"]), json=payload, timeout=15)
        assert r.status_code == 403

    def test_erase_reason_length_validation(self, tokens):
        tm = requests.get(f"{API}/team", headers=H(tokens["level_4"])).json()["team"]
        aid = tm[0]["agent_id"]
        sd = requests.get(f"{API}/dashboard/summary", headers=H(tokens["level_4"])).json()["sales_day"]
        r = requests.post(f"{API}/manager/erase", headers=H(tokens["level_4"]),
                          json={"agent_id": aid, "sales_day": sd, "new_alp": 0, "reason": "short"}, timeout=15)
        assert r.status_code == 400

    def test_erase_flow_and_audit(self, tokens):
        # Find agent with gross > 0
        team = requests.get(f"{API}/team", headers=H(tokens["level_4"])).json()["team"]
        sd = requests.get(f"{API}/dashboard/summary", headers=H(tokens["level_4"])).json()["sales_day"]
        target = next((a for a in team if a["gross_alp"] > 0), None)
        assert target, "No agent with gross alp on seed"
        aid = target["agent_id"]
        original_gross = target["gross_alp"]
        original_net = target["net_alp"]
        new_net = original_net - 500
        r = requests.post(f"{API}/manager/erase", headers=H(tokens["level_4"]),
                          json={"agent_id": aid, "sales_day": sd, "new_alp": new_net,
                                "reason": "Testing erase workflow - audit"}, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True and "audit" in body
        # Verify team now shows gross unchanged, net changed
        team2 = requests.get(f"{API}/team", headers=H(tokens["level_4"])).json()["team"]
        updated = next((a for a in team2 if a["agent_id"] == aid), None)
        assert updated is not None
        assert abs(updated["gross_alp"] - original_gross) < 0.01, "Gross should stay unchanged"
        assert abs(updated["net_alp"] - new_net) < 1.0, f"Net should ~= {new_net}, got {updated['net_alp']}"
        # Verify audit log
        audit = requests.get(f"{API}/manager/audit", headers=H(tokens["level_4"])).json()["items"]
        assert any(a.get("agent_id") == aid for a in audit), "Audit entry missing"


# ---------- VAULT ----------
class TestVault:
    def test_vault_weeks_level_4(self, tokens):
        r = requests.get(f"{API}/vault/weeks", headers=H(tokens["level_4"]), timeout=15)
        assert r.status_code == 200
        weeks = r.json()["weeks"]
        assert len(weeks) == 8

    def test_vault_weeks_forbidden(self, tokens):
        r = requests.get(f"{API}/vault/weeks", headers=H(tokens["level_2"]), timeout=15)
        assert r.status_code == 403

    def test_vault_compare(self, tokens):
        weeks = requests.get(f"{API}/vault/weeks", headers=H(tokens["level_4"])).json()["weeks"]
        a, b = weeks[0]["week_start"], weeks[1]["week_start"]
        r = requests.get(f"{API}/vault/compare", params={"week_a": a, "week_b": b},
                         headers=H(tokens["level_4"]), timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert "delta" in body
        for m in ["gross_alp", "net_alp", "sales", "sits"]:
            assert m in body["delta"]
            assert "pct" in body["delta"][m]


# ---------- SHOUTOUTS ----------
class TestShoutouts:
    def test_shoutouts_visible(self, tokens):
        for lvl in ["level_1", "level_2", "level_3", "level_4"]:
            r = requests.get(f"{API}/shoutouts", headers=H(tokens[lvl]), timeout=15)
            assert r.status_code == 200
            assert "shoutouts" in r.json()
