# BRRS V3.2：免費雲端持久化設定（Render + Supabase）

> GitHub 程式已支援 Supabase PostgreSQL 與私有影片 Storage，但**只有在 Render 設好全部環境變數之後才會啟用**。未設定前仍是 Render 暫存 SQLite／影片，**不保證保留資料**。

## 1. 建立 Supabase 免費專案

1. 前往 https://supabase.com/dashboard ，使用自己的帳號建立 **Free** 專案，專案名稱例如 `brrs`。
2. 在 **Storage → New bucket** 建立 `brrs-videos`，務必選 **Private（不要公開）**。
3. 在 **Project Settings → API Keys** 找到專案的 **URL** 與 **service_role（legacy）金鑰**。
   - 這個金鑰是**秘密**，絕對不要貼在聊天室、GitHub 或公開網址中。
   - 只放在 Render 的 **Environment → Environment Variables**。
4. 在 Supabase 專案中點 **Connect**，複製 **Session pooler**（IPv4、埠 5432）的 Postgres 連線 URI。
   - 連線字串包含資料庫密碼；只放在 Render Environment。
   - 使用 Session pooler，不要使用免費主機可能無法連到的 IPv6 direct connection。

## 2. Render 設定環境變數

在 https://dashboard.render.com/ 開啟 `brrs-demo` → **Environment**，新增：
 
| Key | Value |
|---|---|
| `DATABASE_URL` | Supabase **Session pooler** 連線 URI |
| `SUPABASE_URL` | Supabase Project URL，例如 `https://<project-ref>.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase **service_role** 密鑰（僅在 Render） |
| `SUPABASE_BUCKET` | `brrs-videos` |
| `BRRS_MAX_UPLOAD_MB` | `25` |

儲存環境變數並部署最新 GitHub commit。

## 3. 驗證

開啟：`https://brrs-demo.onrender.com/api/health`

**成功案例**：
```json
{"status":"ok","database":"cloud-postgres","video_storage":"supabase-private","configuration_incomplete":false}
```
首頁會顯示綠色「已啟用雲端資料庫及私人影片儲存」。

**如果看到 `local-ephemeral`**：尚未啟用 Supabase，資料仍可能因 Render 重新部署而遺失。
**如果看到 `not-configured`**：請確認 Storage bucket 名稱與 Private 設定。
**如果看到 503**：檢查 Supabase Session pooler URI、資料庫密碼和服務 Logs，請勿把密碼貼到聊天中。

## 4. 資料、權限與注意事項

- 從 Render 暫存 SQLite 改用 Supabase PostgreSQL 時，會啟用**新的雲端資料庫**；**舊帳號、判例、投票不會自動搬遷**。有重要資料時請先備份並另行規劃遷移。
- 影片必須透過私人 Storage bucket；播放時由後端產生短時效簽署連結。
- 資料庫也由 BRRS 後端存取，不需要讓前端持有 service_role 密鑰。
- 免費 Supabase 目前約 **500 MB 資料庫 + 1 GB 影片/檔案儲存**；本系統每支影片限制 **25 MB**。1 GB 約可存 100 支 10MB 影片，或 40 支 25MB 影片（未計其他檔案）。
- Supabase Free 專案可能在 **一週無活動後暫停**；資料通常可待恢復後存取，但這不是永久在線或自動備份服務。
- 持續使用仍須維護備份及監控配額；500～1000 支原始影片**無法保證**在 1GB 免費空間內存放。
- 刪除群組／判例會連帶刪除其影片、投票與留言；所有刪除都不可復原。
- 不要把 `.env`、SQLite 資料檔或 Supabase 密鑰提交 GitHub。

目前為試用平台；正式讓裁判群組長期使用前，需再做跨重啟資料保留、多帳號權限與容量測試。
