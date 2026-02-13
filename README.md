# llms.txt Generator

Generate [llms.txt](https://llmstxt.org/) files for websites. Add URLs, crawl sites, and download generated files. Sites are monitored and re-crawled on a schedule.

## Local development

```bash
# Backend
cd backend
pip install -r requirements.txt
cp ../.env.example .env   # edit with your DATABASE_URL
uvicorn main:app --reload

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

## Deploy (single service)

Build the frontend, then deploy the backend. The API serves both.

**Build:**
```bash
cd frontend && npm ci && npm run build
```

**Deploy to Render:**
1. Connect your repo
2. Use `render.yaml` (or set Build: `cd frontend && npm ci && npm run build && cd ../backend && pip install -r requirements.txt`, Start: `cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT`)
3. Set env: `DATABASE_URL`, `CRON_SECRET`

**Deploy to Railway:**
1. Connect repo
2. Build: `cd frontend && npm ci && npm run build && cd ../backend && pip install -r requirements.txt`
3. Start: `cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Set env: `DATABASE_URL`, `CRON_SECRET`
