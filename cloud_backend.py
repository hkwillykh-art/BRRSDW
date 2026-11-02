"""BRRS cloud persistence: Supabase Postgres + private Supabase Storage.
All credentials stay server-side in Render environment variables.
"""
import os
import re
from contextlib import contextmanager
from urllib.parse import quote, urljoin
import psycopg
from psycopg.rows import dict_row
import requests

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
BUCKET = os.getenv("SUPABASE_BUCKET", "brrs-videos").strip()
CLOUD_ENABLED = bool(DATABASE_URL and SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)
PARTIAL = any([DATABASE_URL, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY]) and not CLOUD_ENABLED

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
