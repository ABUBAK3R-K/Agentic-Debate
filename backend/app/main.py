import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.friends import router as friends_router, persona_router
from app.api.debates import router as debates_router

# Configure logging
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="PersonaArena API", version="1.0.0")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(friends_router)
app.include_router(persona_router)
app.include_router(debates_router)


@app.get("/")
def read_root():
    return {"message": "Welcome to PersonaArena API"}
