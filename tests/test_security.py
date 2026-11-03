"""Security regression tests for BRRS v4 foundation."""
import uuid
from fastapi.testclient import TestClient
import app

client=TestClient(app.app)

def test_password_rotation_revokes_all_sessions():
    email=f"security-{uuid.uuid4().hex}@example.com"
    original="Original-very-long-passphrase"
    new="Changed-very-long-passphrase"
    assert client.post("/api/register",json={"name":"Security","email":email,"password":original}).status_code==200
    login=lambda password:client.post("/api/login",json={"email":email,"password":password})
    r1,r2=login(original),login(original)
    assert r1.status_code==200 and r2.status_code==200
    first,second=r1.json()["token"],r2.json()["token"]
    assert client.post("/api/me/change-password",json={"current_password":"wrong","new_password":new},
                       headers={"Authorization":"Bearer "+first}).status_code==403
    assert client.post("/api/me/change-password",json={"current_password":original,"new_password":new},
                       headers={"Authorization":"Bearer "+first}).status_code==200
    for token in (first,second):
        assert client.get("/api/me",headers={"Authorization":"Bearer "+token}).status_code==401
    assert login(original).status_code==401
    assert login(new).status_code==200

def test_security_headers_and_password_requirements():
    res=client.get("/")
    assert res.status_code==200
    assert res.headers["x-content-type-options"]=="nosniff"
    assert res.headers["x-frame-options"]=="DENY"
    assert "referrer-policy" in res.headers
    email=f"short-{uuid.uuid4().hex}@example.com"
    r=client.post("/api/register",json={"name":"Security","email":email,"password":"12345678"})
    assert r.status_code==422

def test_login_throttle_blocks_bruteforce():
    email=f"brute-{uuid.uuid4().hex}@example.com"
    for _ in range(8):
        assert client.post("/api/login",json={"email":email,"password":"wrong-passphrase"}).status_code==401
    assert client.post("/api/login",json={"email":email,"password":"wrong-passphrase"}).status_code==429
