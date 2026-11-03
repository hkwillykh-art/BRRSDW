import uuid
from pathlib import Path

from fastapi.testclient import TestClient
import app as brrs
import cloud_backend as storage

client = TestClient(brrs.app)


def register_and_login(name="Tester"):
    email = f"{uuid.uuid4().hex}@example.org"
    password = "test-password-123"
    response = client.post("/api/register", json={"name": name, "email": email, "password": password})
    assert response.status_code == 200, response.text
    response = client.post("/api/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    data = response.json()
    return {"Authorization": "Bearer " + data["token"]}, data["user"]


def test_health_and_r2_adapter(monkeypatch, tmp_path):
    response = client.get("/api/health")
    assert response.status_code == 200, response.text
    assert response.json()["database"] in ("local-ephemeral", "cloud-postgres")

    uploaded = []
    deleted = []
    monkeypatch.setattr(storage, "VIDEO_BACKEND", "r2")
    monkeypatch.setattr(storage, "r2_upload", lambda name, path, mime: uploaded.append((name, mime)))
    monkeypatch.setattr(storage, "r2_signed_url", lambda name, ttl: f"https://signed.invalid/{name}")
    monkeypatch.setattr(storage, "r2_delete", lambda names: deleted.extend(names))
    name = "clip.mp4"
    temp = tmp_path / name
    temp.write_bytes(b"test")
    assert storage.store_video(name, temp, "video/mp4") == "r2:clip.mp4"
    assert uploaded == [("clip.mp4", "video/mp4")]
    assert storage.video_signed_url("r2:clip.mp4") == "https://signed.invalid/clip.mp4"
    assert storage.remove_stored_videos(["r2:clip.mp4"]) == []
    assert deleted == ["clip.mp4"]


def test_case_delete_and_single_vote():
    owner_auth, owner = register_and_login("owner")
    member_auth, member = register_and_login("member")

    r = client.post("/api/groups", headers=owner_auth, json={"name": "Referees"})
    assert r.status_code == 200, r.text
    group_id = r.json()["id"]
    invite = r.json()["invite"]
    assert client.post("/api/groups/join", headers=member_auth, json={"code": invite}).status_code == 200

    r = client.post("/api/cases", headers=member_auth,
                    json={"group_id": group_id, "title": "Contact review", "start": 1.0, "end": 6.0})
    assert r.status_code == 200, r.text
    case_id = r.json()["id"]

    r = client.post(f"/api/cases/{case_id}/votes", headers=member_auth, json={"choice": "正確宣判"})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/cases/{case_id}/votes", headers=member_auth, json={"choice": "錯誤宣判"})
    assert r.status_code == 409

    r = client.post(f"/api/cases/{case_id}/comments", headers=member_auth, json={"body": "Rules analysis"})
    assert r.status_code == 200

    # Only group owner can delete entire group.
    assert client.delete(f"/api/groups/{group_id}", headers=member_auth).status_code == 403

    # Uploaded file is also deleted when case is removed.
    r = client.post(f"/api/cases/{case_id}/video", headers=member_auth,
                    files={"file": ("demo.mp4", b"fake-mp4-for-test", "video/mp4")})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/cases/{case_id}/play", headers=member_auth).status_code == 200

    assert client.delete(f"/api/cases/{case_id}", headers=owner_auth).status_code == 200
    assert client.get(f"/api/cases/{case_id}/discussion", headers=member_auth).status_code == 404
    assert client.delete(f"/api/groups/{group_id}", headers=owner_auth).status_code == 200
