# BRRS — Basketball Referee Review System

🏀 籃球裁判判例分析系統（測試版）

網站：https://brrs-demo.onrender.com/

## 雲端影片儲存（10 GB 免費額度）

已加入 **Cloudflare R2** 私有影片上傳、播放及刪除支援，並保留 **Supabase PostgreSQL** 作為帳號、群組、判例、投票和留言資料庫。

**重要：只上傳程式不會自動啟用雲端儲存。** 請按照 [R2_SETUP.md](R2_SETUP.md) 在 Cloudflare 建立 R2 Standard bucket，再將環境變數設定於 Render。不要將 API 金鑰放到 GitHub 或聊天訊息中。

- 健康檢查：`/api/health`。確認 `database=cloud-postgres` 及 `video_storage=cloudflare-r2-private`。
- 網站目前單支影片 25 MB 上限。
- Cloudflare R2 Standard 每月 10 GB-month 免費額度，**超過可能收費**。請監控用量，並確認 bucket 沒有開啟公開網域。
- 刪除判例時會刪除關聯的投票、留言及影片；群組刪除僅限建立者。
- 每位帳號對同一判例只能投票一次，後端使用複合主鍵限制。
- Render 免費方案可能休眠；舊的 Render 本機檔案和 SQLite 資料**不會自動遷移**到雲端。

## 說明

- [Cloudflare R2 10 GB 設定指南](R2_SETUP.md)
- [Supabase 資料庫設定指南](SUPABASE_SETUP.md)
- [測試版部署說明](README_V3_1.md)

正式提供裁判長期使用前，仍需測試雲端連線、多人權限、重新部署後資料保存及備份作業。
