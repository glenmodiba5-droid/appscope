from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import events, insights, dashboard, auth

app = FastAPI(
    title="AppScope API",
    description="Behind the scenes brain for app builders",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(events.router)
app.include_router(insights.router)
app.include_router(dashboard.router)
app.include_router(auth.router)


@app.get("/")
def root():
    return {"status": "AppScope API is running"}


@app.get("/health")
def health():
    return {"status": "healthy"}
