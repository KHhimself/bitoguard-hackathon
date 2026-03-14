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

`.env.local` 至少需要：

```bash
BITOGUARD_INTERNAL_API_BASE=http://127.0.0.1:8001
BITOGUARD_INTERNAL_API_KEY=bitoguard-dev-key
```

若後端未設定 `BITOGUARD_API_KEY`，可以省略 `BITOGUARD_INTERNAL_API_KEY`。Compose 與部署範本預設會啟用後端 API key，因此前端代理必須帶同一把內部金鑰。
