# BRRS V3.3 — Cloudflare R2 10 GB 影片空間設定

> **狀態：GitHub 程式已加入 Cloudflare R2，但只有在完成下列 Cloudflare / Supabase / Render 設定後才會真正啟用。** 不要把任何密鑰貼在 GitHub 或聊天對話中。

## 目標架構

- Render Free：執行 BRRS 網站（可能休眠）
- Supabase Postgres：裁判帳號、群組、判例、留言、投票。**這個資料庫仍然必須設定**。
- Cloudflare R2 Standard bucket：籃球影片。使用私有 bucket 及 10 分鐘限時播放 URL。
- 若 Cloudflare 尚未設定，但 Supabase Storage 已設定，影片會沿用 Supabase Storage；兩者都沒有時則仍是 Render 暫存空間。

## 第 1 步：申請 Cloudflare R2

1. 登入 https://dash.cloudflare.com ，進入 **R2 Object Storage**。
2. 視介面啟用 R2（可能需要帳單資料）；**請先確認不會啟用需要付費的額外服務**。
3. 建立 bucket，名稱建議 `brrs-videos`，儲存類型選 **Standard**。
4. 維持 **私有**：不要啟用 R2.dev 公開網址或 Public Custom Domain。
5. 在 R2 的 **Manage API Tokens / API Tokens** 建立僅對 `brrs-videos` 有效的 Object Read & Write 憑證，取得 **Access Key ID** 與 **Secret Access Key**。這些是機密，**不要放 GitHub、截圖或聊天內容**。
6. 抄下 Cloudflare **Account ID**（帳戶 ID，不是 API Token）。

Cloudflare 官方文件：
- https://developers.cloudflare.com/r2/get-started/s3/
- https://developers.cloudflare.com/r2/api/tokens/
- https://developers.cloudflare.com/r2/pricing/

## 第 2 步：保留或新建 Supabase Postgres

若已完成 Supabase `DATABASE_URL`，保留設定即可。

若還沒有 Supabase，請依 https://github.com/hkwillykh-art/BRRSDW/blob/main/SUPABASE_SETUP.md 建立免費 Postgres 專案。**這一步不能跳過**；只有 R2 影片空間，無法保證裁判帳號與判例資料不消失。

## 第 3 步：Render 設定

登入 https://dashboard.render.com/ ，進入 `brrs-demo` → **Environment** → 設定下列環境變數：

| Key | Value |
|---|---|
| `DATABASE_URL` | Supabase **Session pooler** PostgreSQL URI（機密） |
| `R2_ACCOUNT_ID` | Cloudflare Account ID |
| `R2_ACCESS_KEY_ID` | R2 Access Key ID（機密） |
| `R2_SECRET_ACCESS_KEY` | R2 Secret Access Key（機密） |
| `R2_BUCKET` | `brrs-videos` |
| `BRRS_MAX_UPLOAD_MB` | `25` |

`R2_ENDPOINT_URL` 選填：大多數 bucket 不必填；若選 EU / US 特定司法轄區，可依 Cloudflare 後台提供的對應 S3 API endpoint 填入。

**不要把上述機密直接貼到 `render.yaml`、GitHub、或 BRRS 網頁。** 在 Render 的 Environment 畫面設定後，儲存並部署最新 GitHub commit。

R2 設定完整時優先使用 R2；舊版 Supabase Storage 憑證可以暫時留著，以播放先前儲存的舊影片。請勿隨意清除舊 bucket 造成影片遺失。

## 第 4 步：確認已啟用

瀏覽 https://brrs-demo.onrender.com/api/health （此狀態頁**不顯示密鑰**）：

```json
{
  "status": "ok",
  "database": "cloud-postgres",
  "video_storage": "cloudflare-r2-private",
  "configuration_incomplete": false
}
```

若看到 `local-ephemeral` 或 `not-configured`，請先不要上傳正式判例；檢查環境變數和 Render Logs。只有健康狀態顯示正確仍不足以保證所有操作正常，還需要實測：上傳影片、播放、刪除、重新部署後仍可播放，以及不同帳號的群組權限和投票限制。

## 重要限制

- Cloudflare R2 **Standard** 每月有 10 GB-month 儲存、100 萬次 Class A、1,000 萬次 Class B 免費額度；超出免費額度可能產生費用，**不是「超出就停止」的硬限制**。
- 10 GB 大約能放 1,000 支每支 10 MB 的影片；若每支 25 MB，約 400 支。這是粗略容量換算。
- 每支影片的上傳上限目前仍是 25 MB，超過需要壓縮或修改後端設定。
- Render 免費主機、Supabase 免費資料庫仍有休眠與使用量限制；請定期備份並監控各平台配額。
- R2 的新影片物件會標記為 `r2:<key>`，既有 Supabase 影片有舊物件鍵；不會自動複製舊影片到 R2。若先前使用 Render 本機暫存，舊影片不會自動移轉。
- 限時播放網址可以在有效期內由取得網址的人開啟；不要將它公開發布。
- 若要確保「完全不會收費」，使用前先了解 R2 的帳單/用量控制；免費額度不是保證零費用。

最後更新：2026-11-03。
