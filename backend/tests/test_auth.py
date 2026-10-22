import pyotp

from tests.conftest import make_client, register


async def test_register_login_logout(client):
    me = await register(client, "alice@example.com", tenant_name="Alice Home", locale="en")
    assert me["role"] == "owner" and me["tenant"]["type"] == "home" and me["tenant"]["plan"]["code"] == "free"
    assert me["user"]["email"] == "alice@example.com"
    assert "se_session" in client.cookies
    assert (await client.get("/api/auth/me")).status_code == 200

    # logout kills the server-side session even if the cookie is replayed
    cookie = client.cookies.get("se_session")
    r = await client.post("/api/auth/logout")
    assert r.status_code == 204
    client.cookies.set("se_session", cookie)
    r = await client.get("/api/auth/me")
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
    assert "message_ar" in r.json()["error"]

    client.cookies.clear()
    r = await client.post("/api/auth/login", json={"email": "ALICE@example.com", "password": "password123"})
    assert r.status_code == 200 and r.json()["user"]["email"] == "alice@example.com"


async def test_duplicate_email_and_bad_password(client):
    await register(client, "dup@example.com")
    r = await client.post("/api/auth/register", json={"email": "dup@example.com", "password": "password123",
                                                       "name": "x", "tenant_name": "x", "locale": "ar"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_taken"
    r = await client.post("/api/auth/register", json={"email": "new@example.com", "password": "short", "name": "x",
                                                       "tenant_name": "x", "locale": "ar"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    r = await client.post("/api/auth/login", json={"email": "dup@example.com", "password": "wrong-password"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_credentials"
    r = await client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "whatever123"})
    assert r.status_code == 401


async def test_login_rate_limit(client):
    await register(client, "rl@example.com")
    client.cookies.clear()
    for _ in range(8):
        r = await client.post("/api/auth/login", json={"email": "rl@example.com", "password": "bad-password"})
        assert r.status_code == 401
    r = await client.post("/api/auth/login", json={"email": "rl@example.com", "password": "password123"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"


async def test_totp_flow(client):
    await register(client, "tf@example.com")
    s = (await client.post("/api/auth/totp/setup")).json()
    assert s["otpauth_url"].startswith("otpauth://totp/")
    totp = pyotp.TOTP(s["secret"])
    assert (await client.post("/api/auth/totp/enable", json={"code": "000000"})).status_code == 401
    assert (await client.post("/api/auth/totp/enable", json={"code": totp.now()})).status_code == 200
    assert (await client.get("/api/auth/me")).json()["user"]["totp_enabled"] is True

    c2 = make_client()
    r = await c2.post("/api/auth/login", json={"email": "tf@example.com", "password": "password123"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "totp_required"
    r = await c2.post("/api/auth/login", json={"email": "tf@example.com", "password": "password123", "totp_code": "123456"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_totp"
    r = await c2.post("/api/auth/login", json={"email": "tf@example.com", "password": "password123", "totp_code": totp.now()})
    assert r.status_code == 200

    assert (await client.post("/api/auth/totp/disable", json={"code": "111111"})).status_code == 401
    assert (await client.post("/api/auth/totp/disable", json={"code": totp.now()})).status_code == 200
    assert (await client.get("/api/auth/me")).json()["user"]["totp_enabled"] is False
    await c2.aclose()


async def test_patch_me_and_password_change_revokes_other_sessions(client):
    await register(client, "pm@example.com")
    other = make_client()
    await other.post("/api/auth/login", json={"email": "pm@example.com", "password": "password123"})
    assert (await other.get("/api/auth/me")).status_code == 200
    r = await client.patch("/api/auth/me", json={"name": "New Name", "locale": "en"})
    assert r.json()["user"]["name"] == "New Name" and r.json()["user"]["locale"] == "en"
    r = await client.patch("/api/auth/me", json={"password": "newpassword99"})
    assert r.status_code == 401  # needs current_password
    r = await client.patch("/api/auth/me", json={"password": "newpassword99", "current_password": "password123"})
    assert r.status_code == 200
    assert (await other.get("/api/auth/me")).status_code == 401
    assert (await client.get("/api/auth/me")).status_code == 200
    await other.aclose()


async def test_unauthenticated_and_garbage_cookie(client):
    assert (await client.get("/api/devices")).status_code == 401
    client.cookies.set("se_session", "not-a-jwt")
    assert (await client.get("/api/sites")).status_code == 401


async def test_health_and_docs(client):
    assert (await client.get("/api/health")).json()["ok"] is True
    assert (await client.get("/api/docs")).status_code == 200
