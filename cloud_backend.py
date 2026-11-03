"""BRRS cloud persistence: Supabase Postgres + Cloudflare R2 / Supabase Storage.
All credentials stay server-side in Render environment variables.
"""
import os
import re
from contextlib import contextmanager
from urllib.parse import quote, urljoin
import psycopg
from psycopg.rows import dict_row
import requests
import boto3
from botocore.config import Config

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
BUCKET = os.getenv("SUPABASE_BUCKET", "brrs-videos").strip()
# Database and file storage are configured independently.
DATABASE_ENABLED = bool(DATABASE_URL)
SUPABASE_STORAGE_ENABLED = bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "").strip()
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "").strip()
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
R2_BUCKET = os.getenv("R2_BUCKET", "brrs-videos").strip()
R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL", "").strip()  # optional jurisdiction endpoint
R2_ENABLED = bool(R2_ACCOUNT_ID and R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY and R2_BUCKET)
R2_PARTIAL = any([R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY]) and not R2_ENABLED
CLOUD_ENABLED = DATABASE_ENABLED  # backwards compatible name used by app.py
VIDEO_BACKEND = "r2" if DATABASE_ENABLED and R2_ENABLED else (
    "supabase" if DATABASE_ENABLED and SUPABASE_STORAGE_ENABLED else "local"
)
PARTIAL = (R2_PARTIAL or (bool(SUPABASE_URL) != bool(SUPABASE_SERVICE_ROLE_KEY))
           or (bool(R2_ENABLED) and not DATABASE_ENABLED)
           or (DATABASE_ENABLED and VIDEO_BACKEND == "local"))


class PostgresCompat:
    def __init__(self, database):
        self.database = database
    def execute(self, sql, args=()):
        sql = sql.replace("?", "%s")
        sql = re.sub(r'\bgroups\b', '"groups"', sql)
        if "INSERT OR IGNORE INTO" in sql:
            sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO") + " ON CONFLICT DO NOTHING"
        return self.database.execute(sql, args)
    def executescript(self, script):
        for sql in script.split(";"):
            if sql.strip():
                self.execute(sql)

@contextmanager
def postgres_conn():
    # Session pooler on port 5432 supports IPv4 on Render Free.
    with psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=15,
                         sslmode="require", prepare_threshold=None) as db:
        yield PostgresCompat(db)

def storage_headers(extra=None):
    headers = {"apikey": SUPABASE_SERVICE_ROLE_KEY,
               "Authorization": "Bearer " + SUPABASE_SERVICE_ROLE_KEY}
    if extra:
        headers.update(extra)
    return headers

def storage_base():
    return SUPABASE_URL + "/storage/v1"

def private_bucket_ready():
    response = requests.get(storage_base() + "/bucket/" + quote(BUCKET, safe=""),
                            headers=storage_headers(), timeout=(10, 20))
    if not response.ok:
        return False
    data = response.json()
    return data.get("public") is False

def upload_object(object_key, filepath, mime):
    url = storage_base() + "/object/" + quote(BUCKET, safe="") + "/" + quote(object_key, safe="/")
    with open(filepath, "rb") as data:
        response = requests.post(url, headers=storage_headers({"Content-Type": mime, "x-upsert": "false"}),
                                 data=data, timeout=(15, 180))
    if not response.ok:
        raise RuntimeError("雲端儲存上傳失敗（HTTP %s）：%s" % (response.status_code, response.text[:180]))

def signed_media_url(object_key, ttl=600):
    url = storage_base() + "/object/sign/" + quote(BUCKET, safe="") + "/" + quote(object_key, safe="/")
    response = requests.post(url, headers=storage_headers({"Content-Type": "application/json"}),
                             json={"expiresIn": ttl}, timeout=(15, 30))
    if not response.ok:
        raise RuntimeError("建立雲端影片播放連結失敗（HTTP %s）" % response.status_code)
    signed = response.json().get("signedURL") or response.json().get("signedUrl")
    if not signed:
        raise RuntimeError("雲端儲存未提供播放連結")
    if signed.startswith("https://"):
        return signed
    if signed.startswith("/storage/v1/"):
        return SUPABASE_URL + signed
    if signed.startswith("/object/"):
        return storage_base() + signed
    return urljoin(storage_base() + "/", signed.lstrip("/"))

def remove_objects(object_keys):
    keys = [key for key in object_keys if key]
    for i in range(0, len(keys), 100):
        response = requests.delete(storage_base() + "/object/" + quote(BUCKET, safe=""),
                                   headers=storage_headers({"Content-Type": "application/json"}),
                                   json={"prefixes": keys[i:i+100]}, timeout=(15, 60))
        if not response.ok:
            raise RuntimeError("刪除雲端影片失敗（HTTP %s）" % response.status_code)

def r2_client():
    if not R2_ENABLED:
        raise RuntimeError("Cloudflare R2 is not configured")
    endpoint = R2_ENDPOINT_URL or "https://" + R2_ACCOUNT_ID + ".r2.cloudflarestorage.com"
    if not endpoint.startswith("https://"):
        raise RuntimeError("R2 endpoint must use HTTPS")
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name="auto",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )

def r2_bucket_ready():
    if not R2_ENABLED:
        return False
    r2_client().head_bucket(Bucket=R2_BUCKET)
    return True

def r2_upload(key, path, mime):
    r2_client().upload_file(str(path), R2_BUCKET, key, ExtraArgs={"ContentType": mime})

def r2_signed_url(key, ttl=600):
    return r2_client().generate_presigned_url(
        "get_object", Params={"Bucket": R2_BUCKET, "Key": key}, ExpiresIn=ttl
    )

def r2_delete(keys):
    keys = [key for key in keys if key]
    for i in range(0, len(keys), 1000):
        r2_client().delete_objects(
            Bucket=R2_BUCKET,
            Delete={"Objects": [{"Key": key} for key in keys[i:i + 1000]], "Quiet": True},
        )

def stored_video_backend(key):
    if key.startswith("r2:"):
        return "r2", key[3:]
    if key.startswith("sb:"):
        return "supabase", key[3:]
    # Legacy unprefixed cloud keys are Supabase objects.
    return ("supabase" if SUPABASE_STORAGE_ENABLED and DATABASE_ENABLED else "local"), key

def store_video(name, filepath, mime):
    if VIDEO_BACKEND == "r2":
        r2_upload(name, filepath, mime)
        return "r2:" + name
    if VIDEO_BACKEND == "supabase":
        upload_object(name, filepath, mime)
        return "sb:" + name
    return name

def video_signed_url(key, ttl=600):
    backend, name = stored_video_backend(key)
    if backend == "r2":
        return r2_signed_url(name, ttl)
    if backend == "supabase":
        return signed_media_url(name, ttl)
    return None

def remove_stored_videos(keys):
    r2_keys, sb_keys, local_keys = [], [], []
    for key in keys:
        if not key: continue
        backend, name = stored_video_backend(key)
        if backend == "r2": r2_keys.append(name)
        elif backend == "supabase": sb_keys.append(name)
        else: local_keys.append(name)
    if r2_keys: r2_delete(r2_keys)
    if sb_keys: remove_objects(sb_keys)
    return local_keys
