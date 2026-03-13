# BitoGuard Frontend

`bitoguard_frontend` 是 BitoGuard 的正式前端，使用 Next.js App Router，透過 `/api/backend/*` 代理到 `bitoguard_core` internal API。

## 安裝

```bash
cd bitoguard_frontend
npm install
cp .env.example .env.local
```

## 開發模式

先啟動 `bitoguard_core` internal API：

```bash
cd bitoguard_core
. .venv/bin/activate
PYTHONPATH=. uvicorn api.main:app --reload --port 8001
```

再啟動前端：

```bash
cd bitoguard_frontend
npm run dev
```

開啟 <http://localhost:3000>。

## 環境變數

`.env.local` 目前只需要：

```bash
BITOGUARD_INTERNAL_API_BASE=http://127.0.0.1:8001
```

若只想看已內建的 demo 資料，不需要先跑 `bitoguard_mock_api`。目前 sync pipeline 預設直接讀取 BitoPro AWS Event API；`bitoguard_mock_api` 只保留給本地 fixture 驗證或離線開發。
