from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

# Import your batch monitor router
from live_batch_monitor import router as batch_monitor_router

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app instance
app = FastAPI(
    title="NHIS Batch Processing API",
    description="API for monitoring NHIS batch processing",
    version="2.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include the batch monitor router
app.include_router(batch_monitor_router)

# Root endpoint for health check
@app.get("/")
async def root():
    return {"message": "NHIS Batch Processing API is running", "version": "2.0.0"}

# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "nhis-batch-api"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)