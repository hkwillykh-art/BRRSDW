import uuid
from fastapi.testclient import TestClient
import app

client=TestClient(app.app)

def account(name):
    email=f"{uuid.uuid4().hex}@example.org"
    password="Sufficiently-long-password-321"
    assert client.post("/api/register",json={"name":name,"email":email,"password":password}).status_code==200
    login=client.post("/api/login",json={"email":email,"password":password})
    assert login.status_code==200
    return {"Authorization":"Bearer "+login.json()["token"]}

def test_group_owner_controls_invites_and_membership():
    owner=account("Leader")
    member=account("Official")
    outsider=account("Outsider")
    r=client.post("/api/groups",headers=owner,json={"name":"Private reviews"})
    assert r.status_code==200
    gid,invite=r.json()["id"],r.json()["invite"]
    assert client.post("/api/groups/join",headers=member,json={"code":invite}).status_code==200
    owner_groups=client.get("/api/groups",headers=owner).json()
    member_groups=client.get("/api/groups",headers=member).json()
    assert next(g for g in owner_groups if g["id"]==gid)["invite"]==invite
    assert next(g for g in member_groups if g["id"]==gid)["invite"] is None
    assert client.get(f"/api/groups/{gid}/members",headers=outsider).status_code==403
    assert len(client.get(f"/api/groups/{gid}/members",headers=owner).json())==2
    assert client.post(f"/api/groups/{gid}/rotate-invite",headers=member).status_code==403
    newer=client.post(f"/api/groups/{gid}/rotate-invite",headers=owner)
    assert newer.status_code==200
    assert newer.json()["invite"]!=invite
    assert client.post("/api/groups/join",headers=outsider,json={"code":invite}).status_code==404
    assert client.post("/api/groups/join",headers=outsider,json={"code":newer.json()["invite"]}).status_code==200
    people=client.get(f"/api/groups/{gid}/members",headers=owner).json()
    member_uid=next(x["id"] for x in people if x["name"]=="Official")
    assert client.delete(f"/api/groups/{gid}/members/{member_uid}",headers=outsider).status_code==403
    assert client.delete(f"/api/groups/{gid}/members/{member_uid}",headers=owner).status_code==200
    assert client.get(f"/api/groups/{gid}/members",headers=member).status_code==403
