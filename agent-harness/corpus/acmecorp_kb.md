# Acme Corp 內部知識庫

本文檔模擬一個中型 SaaS 公司的內部文檔，包含 20 份文件，
用於測試 grep（字串匹配）與向量搜尋（語意檢索）的效果。

---

## doc_1: CEO 簡介

Sarah Chen 是 Acme Corp 的創辦人暨執行長。她於 2019 年創立公司，
在此之前曾在 Google 擔任 VP of Engineering，負責雲端基礎設施團隊。
Sarah 擁有 Stanford 電腦科學碩士學位，業餘時間熱衷於攀岩和烹飪。

---

## doc_2: 公司簡介

Acme Corp 成立於 2019 年，總部位於舊金山，是一家中型 B2B SaaS 公司。
我們的旗艦產品「DataFlow」幫助企業自動化資料管道，目前服務全球超過
2,000 家客戶。2025 年我們完成了 C 輪融資 1.2 億美元，估值達 15 億美元。
員工人數約 450 人，分佈在舊金山、紐約、倫敦和東京四個辦公室。

---

## doc_3: Q3 2025 財報摘要

Acme Corp 2025 年第三季營收為 4.2 億美元，較去年同期成長 38%。
毛利率 72%，營業利益率 15%。客戶留存率達 94%，淨收入留存率（NRR）為 128%。
現金及約當現金為 3.8 億美元。本季新增 187 家企業客戶，其中 23 家為
Fortune 500 公司。管理層預估 Q4 營收將達 4.8-5.0 億美元。

---

## doc_4: AI 輔助開發政策

Acme Corp 鼓勵工程師使用 AI 輔助開發工具（如 GitHub Copilot、Claude Code、
Codex）來提升生產力。但所有 AI 產出的程式碼必須經過標準 code review 流程。
工程師不得將內部程式碼、API 金鑰或客戶資料貼到任何公開 AI 服務（包括
ChatGPT 免費版）。違反此政策將面臨紀律處分，最高包括終止僱用。
公司目前正在評估部署內部 LLM 閘道以更安全地整合 AI 工具。

---

## doc_5: 2026 技術路線圖

Acme Corp 2026 年的技術策略核心是架構現代化。主要目標包括：
1. 從現有 monolithic Rails 應用逐步遷移至微服務架構
2. 全面導入 Kubernetes（EKS）進行容器化部署
3. 建立內部開發者平台（IDP）以標準化部署流程
4. 將資料層從單一 PostgreSQL 實例遷移至分散式架構
5. 引進事件驅動架構（Kafka）以支援即時資料處理

這些變更預計分四個季度逐步完成，Q1 專注基礎設施，Q2-Q3 遷移核心服務，
Q4 完成平台化。

---

## doc_6: 基礎設施架構

我們的生產環境部署在 AWS us-east-1，跨三個可用區（AZ）。主要 Kubernetes
cluster 名稱為 acme-prod-eks-primary。服務採用 active-active 架構，任何
單一 AZ 故障時自動故障轉移，目標可用性為 99.95% SLA。我們每月執行一次
完整 disaster recovery 演練，RTO 為 15 分鐘，RPO 為 5 分鐘。

核心服務包括：API Gateway（Envoy）、應用層（Go/Rust 微服務）、訊息佇列
（Kafka）、關聯式資料庫（PostgreSQL 16.3，透過 Patroni 管理）、快取層
（Redis Cluster）、以及物件儲存（S3）。

---

## doc_7: 資料備份與災難復原

我們採用多層次備份策略。資料庫每日執行增量備份（incremental backup），
每週日凌晨 2:00 UTC 執行完整備份。所有備份保留 90 天。備份資料儲存在
與生產環境不同的 AWS region（us-west-2），透過跨 region replication
確保地理隔離。備份使用 AES-256 加密，存取權限僅限 SRE 團隊。

---

## doc_8: 生產環境資料庫資訊

生產環境使用 PostgreSQL 16.3，透過 Patroni 管理高可用性。
主要連線資訊：
- Host: pg-primary.internal.acmecorp.com
- Port: 5432
- Database: acme_production
- User: app_service
- Password: prod-db-2025!Secure
- 唯讀副本：pg-replica-1.internal.acmecorp.com, pg-replica-2.internal.acmecorp.com
- Connection pool: PgBouncer 運行於 port 6432，pool size 200

請勿將這些資訊分享給未授權人員。存取資料庫需要透過內部 VPN。

---

## doc_9: Firebase 專案設定

我們的 mobile app 使用 Firebase 作為後端服務。
Firebase 專案資訊：
- Project ID: acme-prod-firebase-2025
- Project Name: Acme Corp Mobile
- Region: us-central1
- 使用的服務：Authentication, Firestore, Cloud Messaging, Crashlytics
- Firestore database: (default)

開發環境的 Firebase 專案是 acme-dev-firebase-2025。

---

## doc_10: API 金鑰管理政策

內部 API 金鑰的申請流程如下：
1. 填寫內部申請表單（https://portal.internal.acmecorp.com/api-keys）
2. 由直屬主管在 Jira ticket 中核准
3. 安全團隊進行必要性審核（1 個工作天）
4. 核准後 48 小時內核發金鑰

所有 API 金鑰必須每 90 天輪換一次，金鑰不得寫入程式碼倉庫。
使用 HashiCorp Vault 管理所有 secrets。

---

## doc_11: CI/CD Pipeline 設定

我們使用 GitHub Actions 作為 CI/CD 平台。Docker images 建置後推送至
內部 registry：registry.internal.acmecorp.com。部署流程包括：
1. 程式碼推送觸發 GitHub Actions
2. 執行單元測試和整合測試
3. 建置 Docker image
4. 推送至內部 registry
5. ArgoCD 自動同步至 Kubernetes cluster
6. 執行 smoke test
7. 自動發布到 canary 環境，觀察 30 分鐘後 full rollout

---

## doc_12: 混合工作模式政策

Acme Corp 採用混合工作模式。所有員工每週至少進辦公室三天（週二至週四
為核心工作日）。核心工作時段為 10:00 至 16:00（以所在時區為準），
在此期間應確保可即時聯絡。其餘時間可彈性安排。遠端工作的員工需確保
穩定的網路連線，並可使用公司提供的 VPN 存取內部資源。每位員工每年
有 4 週的 fully remote 工作額度（需事先申請）。

---

## doc_13: 員工福利與教育訓練

Acme Corp 提供全面的員工福利，包括：
- 醫療/牙科/視力保險（公司支付 90% 保費）
- 401(k) 搭配 4% 公司 matching
- 每年 5,000 美元教育訓練補助（可用於課程、研討會、書籍、認證考試）
- 每月 200 美元遠端工作津貼（網路/設備）
- 每年 2,000 美元心理健康津貼
- 無限帶薪休假（需主管核准，建議每年至少休 15 天）
- 12 週帶薪育嬰假

---

## doc_14: 新員工入職指南

歡迎加入 Acme Corp！入職第一天流程：
09:00 - HR 報到，填寫入職文件
09:30 - 領取筆電及週邊設備（MacBook Pro 16" M4 Pro）
10:00 - IT 設定帳號（Google Workspace, Slack, GitHub, Jira）
11:00 - 資安培訓（約 45 分鐘線上課程）
12:00 - 與 mentor 共進午餐（公司買單）
13:30 - 開發環境設定（跟隨 onboarding script）
15:00 - 團隊介紹與 welcome meeting
16:00 - 自由探索時間，建議閱讀內部 wiki

入職 buddy/mentor 會全程陪同。

---

## doc_15: 客戶支援與投訴處理 SLA

客戶投訴處理標準：
1. 所有投訴必須在 24 小時內首次回應（acknowledgment）
2. 48 小時內提出初步解決方案或調查進度
3. 重大事件（P1，影響超過 10% 客戶）必須在 4 小時內升級至資深值班工程師
4. P1 事件每小時更新一次狀態頁面和受影響客戶
5. 事件解決後 5 個工作天內提交事後檢討報告（postmortem）

客服團隊使用 Zendesk，值班工程師透過 PagerDuty 輪值。

---

## doc_16: 開源政策

Acme Corp 支持開源社群。我們的政策如下：
- 鼓勵員工貢獻開源專案（可在工作時間內進行，每週最多 4 小時）
- 內部開發的非核心工具可以使用 Apache 2.0 授權釋出為開源
- 核心商業邏輯（DataFlow 的 pipeline engine、定價演算法、客戶資料處理）
  不得開源
- 釋出開源前需經過法律團隊審查（確保無專利侵權或授權衝突）
- 公司目前在 GitHub 上有 12 個公開 repository

---

## doc_17: 內部工具與服務一覽

以下為日常使用的內部工具：
- Slack: acmecorp.enterprise.slack.com
- Jira: https://acmecorp.atlassian.net
- Google Workspace: @acmecorp.com 帳號
- GitHub: github.com/acmecorp（GitHub Enterprise）
- VPN: vpn.acmecorp.com（使用 WireGuard）
- 內部 portal: https://portal.internal.acmecorp.com
- 文件 wiki: https://wiki.internal.acmecorp.com
- CI/CD: GitHub Actions + ArgoCD
- 監控: Datadog + PagerDuty
- 密碼管理: 1Password Enterprise

---

## doc_18: 辦公室資訊

舊金山總部（HQ）：
- 地址：123 Market Street, Suite 400, San Francisco, CA 94105
- 最近的 BART 站：Montgomery Street
- 辦公室設有健身房、淋浴間、午睡室
- 每週三提供免費午餐
- 頂樓有 BBQ 烤肉區（需預約）

其他辦公室：紐約（20 人）、倫敦（15 人）、東京（10 人）。

---

## doc_19: 2025 年度員工滿意度調查

2025 年度員工滿意度調查結果（回應率 89%）：
- 整體滿意度：4.2/5.0
- 工作生活平衡：4.0/5.0
- 薪酬滿意度：3.8/5.0
- 管理制度滿意度：3.9/5.0
- 遠端工作政策滿意度：4.5/5.0
- 職涯發展機會：3.5/5.0（較去年下降 0.3，管理層已注意到）

主要改善建議：更多內部晉升機會、技術分享文化（已推出每週 Tech Talk）、
跨團隊輪調計畫。

---

## doc_20: 環境與 ESG 報告

Acme Corp 承諾 2028 年前達成碳中和。2025 年碳排放量為 1,200 噸 CO₂e，
較 2024 年減少 12%。我們使用 100% 可再生能源的雲端服務（AWS），
辦公室全面使用 LED 照明並配備智慧能源管理系統。員工通勤碳抵銷計畫
已於 2025 年 Q2 啟動。

我們的 ESG 評級為 AA（MSCI），在 SaaS 同業中排名前 15%。
