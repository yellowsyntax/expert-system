# live_batch_monitor.py
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.responses import StreamingResponse
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import json
import asyncio
import logging
from pydantic import BaseModel
from neon_db_connection import get_nhis_queries
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v2/batch-monitor", tags=["Batch Processing Monitor"])


def json_serializer(obj):
    """JSON serializer function that handles datetime objects"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

def safe_json_dumps(data):
    """Safely convert data to JSON string, handling datetime objects"""
    return json.dumps(data, default=json_serializer)

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.batch_subscribers: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, batch_id: str = None):
        await websocket.accept()
        self.active_connections.append(websocket)
        
        if batch_id:
            if batch_id not in self.batch_subscribers:
                self.batch_subscribers[batch_id] = []
            self.batch_subscribers[batch_id].append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        
        for batch_id, subscribers in self.batch_subscribers.items():
            if websocket in subscribers:
                subscribers.remove(websocket)

    async def send_to_batch_subscribers(self, batch_id: str, message: dict):
        if batch_id in self.batch_subscribers:
            disconnected = []
            for connection in self.batch_subscribers[batch_id]:
                try:
                    await connection.send_text(safe_json_dumps(message))
                except:
                    disconnected.append(connection)
            
            for conn in disconnected:
                self.disconnect(conn)

    async def broadcast_to_all(self, message: dict):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(safe_json_dumps(message))
            except:
                disconnected.append(connection)
        
        for conn in disconnected:
            self.disconnect(conn)

manager = ConnectionManager()

# Global flag to track if monitoring is running
monitoring_active = False

class BatchProgressUpdate(BaseModel):
    batch_id: str
    total_claims: int
    processed_claims: int
    approved_claims: int
    rejected_claims: int
    flagged_claims: int
    error_claims: int
    percentage_complete: float
    processing_status: str
    current_claim: Optional[str] = None
    processing_rate: Optional[float] = None
    estimated_completion: Optional[datetime] = None
    started_at: Optional[datetime] = None
    last_updated: datetime

class ClaimProgressUpdate(BaseModel):
    encounter_id: str
    batch_id: str
    old_status: str
    new_status: str
    processed_by: str
    processing_stage: str
    updated_at: datetime

@router.websocket("/ws/batch/{batch_id}")
async def websocket_batch_monitor(websocket: WebSocket, batch_id: str):
    await manager.connect(websocket, batch_id)
    try:
        queries = await get_nhis_queries()
        initial_progress = await get_batch_progress(batch_id, queries)
        await websocket.send_text(safe_json_dumps({
            "type": "initial_status",
            "data": initial_progress.dict()
        }))
        
        # Keep connection alive and handle incoming messages
        while True:
            try:
                # Set a timeout to prevent blocking indefinitely
                data = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                # Handle any incoming messages if needed
                logger.debug(f"Received message from client: {data}")
            except asyncio.TimeoutError:
                # No message received, continue loop
                continue
            except WebSocketDisconnect:
                break
                
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for batch {batch_id}")
    except Exception as e:
        logger.error(f"WebSocket error for batch {batch_id}: {e}")
    finally:
        manager.disconnect(websocket)

@router.websocket("/ws/all-batches")
async def websocket_all_batches(websocket: WebSocket):
    global monitoring_active
    await manager.connect(websocket)
    try:
        queries = await get_nhis_queries()
        active_batches = await get_all_active_batches(queries)
        await websocket.send_text(safe_json_dumps({
            "type": "all_batches_status",
            "data": active_batches
        }))
        
        # Start monitoring if not already active
        if not monitoring_active:
            monitoring_active = True
            asyncio.create_task(monitor_all_batches_task())
        
        # Keep connection alive and handle incoming messages
        while True:
            try:
                # Set a timeout to prevent blocking indefinitely
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)  # Increased timeout
                # Handle any incoming messages if needed
                logger.debug(f"Received message from client: {data}")
                
                # Handle ping messages to keep connection alive
                if data.strip() == '{"type":"ping"}':
                    await websocket.send_text(safe_json_dumps({"type": "pong"}))
                    
            except asyncio.TimeoutError:
                # Send heartbeat to check if connection is still alive
                try:
                    await websocket.send_text(safe_json_dumps({"type": "heartbeat"}))
                except:
                    break
                continue
            except WebSocketDisconnect:
                break
                
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for all batches monitor")
    except Exception as e:
        logger.error(f"WebSocket error for all batches monitor: {e}")
    finally:
        manager.disconnect(websocket)

@router.get("/sse/batch/{batch_id}")
async def stream_batch_progress(batch_id: str):
    async def generate_updates():
        last_percentage = 0
        queries = await get_nhis_queries()
        
        while True:
            try:
                progress = await get_batch_progress(batch_id, queries)
                
                if abs(progress.percentage_complete - last_percentage) >= 1 or progress.percentage_complete >= 100:
                    yield f"data: {safe_json_dumps(progress.dict())}\n\n"
                    last_percentage = progress.percentage_complete
                
                if progress.percentage_complete >= 100:
                    yield f"data: {safe_json_dumps({'status': 'complete', 'batch_id': batch_id})}\n\n"
                    break
                
                await asyncio.sleep(3)
                
            except Exception as e:
                logger.error(f"SSE error for batch {batch_id}: {e}")
                yield f"data: {safe_json_dumps({'error': str(e)})}\n\n"
                break
    
    return StreamingResponse(
        generate_updates(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        }
    )

@router.get("/batch-progress/{batch_id}")
async def get_batch_progress_rest(batch_id: str):
    queries = await get_nhis_queries()
    return await get_batch_progress(batch_id, queries)

@router.get("/active-batches")
async def get_active_batches_rest():
    queries = await get_nhis_queries()
    return await get_all_active_batches(queries)

@router.get("/batch-history")
async def get_batch_history(limit: int = 50):
    queries = await get_nhis_queries()
    
    query = """
    SELECT 
        batch_id,
        COUNT(*) as total_claims,
        COUNT(CASE WHEN claim_status = 'processed' THEN 1 END) as processed_claims,
        COUNT(CASE WHEN processed_status = 'approved' THEN 1 END) as approved_claims,
        COUNT(CASE WHEN processed_status = 'rejected' THEN 1 END) as rejected_claims,
        COUNT(CASE WHEN processed_status = 'flagged' THEN 1 END) as flagged_claims,
        MIN(processing_started_at) as started_at,
        MAX(processing_completed_at) as completed_at,
        CASE 
            WHEN COUNT(CASE WHEN claim_status = 'submitted' THEN 1 END) = 0 THEN 'completed'
            WHEN MIN(processing_started_at) IS NOT NULL THEN 'processing'
            ELSE 'pending'
        END as status
    FROM claims_v3 
    WHERE batch_id IS NOT NULL 
    GROUP BY batch_id
    ORDER BY MAX(COALESCE(processing_completed_at, processing_started_at, created_at)) DESC
    LIMIT $1
    """
    
    result = await queries.db.fetch_all(query, limit)
    batches = []
    
    for row in result:
        percentage = (row['processed_claims'] / row['total_claims'] * 100) if row['total_claims'] > 0 else 0
        
        processing_time = None
        if row['started_at'] and row['completed_at']:
            processing_time = (row['completed_at'] - row['started_at']).total_seconds()
        
        batches.append({
            "batch_id": row['batch_id'],
            "total_claims": row['total_claims'],
            "processed_claims": row['processed_claims'],
            "approved_claims": row['approved_claims'],
            "rejected_claims": row['rejected_claims'],
            "flagged_claims": row['flagged_claims'],
            "percentage_complete": round(percentage, 2),
            "status": row['status'],
            "started_at": row['started_at'],
            "completed_at": row['completed_at'],
            "processing_time_seconds": processing_time
        })
    
    return batches

async def get_batch_progress(batch_id: str, queries) -> BatchProgressUpdate:
    query = """
    SELECT 
        COUNT(*) as total_claims,
        COUNT(CASE WHEN claim_status = 'processed' THEN 1 END) as processed_claims,
        COUNT(CASE WHEN processed_status = 'approved' THEN 1 END) as approved_claims,
        COUNT(CASE WHEN processed_status = 'rejected' THEN 1 END) as rejected_claims,
        COUNT(CASE WHEN processed_status = 'flagged' THEN 1 END) as flagged_claims,
        COUNT(CASE WHEN claim_status = 'submitted' THEN 1 END) as pending_claims,
        MIN(processing_started_at) as started_at,
        MAX(processing_completed_at) as last_completed_at,
        MAX(updated_at) as last_updated
    FROM claims_v3 
    WHERE batch_id = $1
    """
    
    result = await queries.db.fetch_one(query, batch_id)
    
    if not result or result['total_claims'] == 0:
        return BatchProgressUpdate(
            batch_id=batch_id,
            total_claims=0,
            processed_claims=0,
            approved_claims=0,
            rejected_claims=0,
            flagged_claims=0,
            error_claims=0,
            percentage_complete=0,
            processing_status="not_found",
            last_updated=datetime.now()
        )
    
    percentage = (result['processed_claims'] / result['total_claims'] * 100) if result['total_claims'] > 0 else 0
    
    if result['processed_claims'] == result['total_claims']:
        status = "completed"
    elif result['processed_claims'] > 0 and result['started_at']:
        status = "processing" 
    elif result['pending_claims'] > 0:
        status = "pending"
    else:
        status = "unknown"
    
    current_claim_query = """
    SELECT encounter_id 
    FROM claims_v3 
    WHERE batch_id = $1 
    AND processing_started_at IS NOT NULL 
    AND processing_completed_at IS NULL 
    ORDER BY processing_started_at DESC 
    LIMIT 1
    """
    
    current_result = await queries.db.fetch_one(current_claim_query, batch_id)
    current_claim = current_result['encounter_id'] if current_result else None
    
    processing_rate = None
    estimated_completion = None
    
    if result['started_at'] and result['processed_claims'] > 0:
        elapsed_time = (datetime.now() - result['started_at']).total_seconds()
        if elapsed_time > 0:
            processing_rate = (result['processed_claims'] * 60) / elapsed_time
            
            remaining_claims = result['total_claims'] - result['processed_claims']
            if processing_rate > 0 and remaining_claims > 0:
                estimated_minutes = remaining_claims / processing_rate
                estimated_completion = datetime.now() + timedelta(minutes=estimated_minutes)
    
    return BatchProgressUpdate(
        batch_id=batch_id,
        total_claims=result['total_claims'],
        processed_claims=result['processed_claims'],
        approved_claims=result['approved_claims'],
        rejected_claims=result['rejected_claims'],
        flagged_claims=result['flagged_claims'],
        error_claims=0,
        percentage_complete=round(percentage, 2),
        processing_status=status,
        current_claim=current_claim,
        processing_rate=round(processing_rate, 2) if processing_rate else None,
        estimated_completion=estimated_completion,
        started_at=result['started_at'],
        last_updated=result['last_updated'] or datetime.now()
    )

async def get_all_active_batches(queries) -> List[Dict[str, Any]]:
    query = """
    SELECT 
        batch_id,
        COUNT(*) as total_claims,
        COUNT(CASE WHEN claim_status = 'processed' THEN 1 END) as processed_claims,
        COUNT(CASE WHEN processed_status = 'approved' THEN 1 END) as approved_claims,
        COUNT(CASE WHEN processed_status = 'rejected' THEN 1 END) as rejected_claims,
        COUNT(CASE WHEN processed_status = 'flagged' THEN 1 END) as flagged_claims,
        COUNT(CASE WHEN claim_status = 'submitted' THEN 1 END) as pending_claims,
        MIN(processing_started_at) as started_at,
        MAX(processing_completed_at) as completed_at,
        MAX(updated_at) as last_updated,
        CASE 
            WHEN COUNT(CASE WHEN claim_status = 'submitted' THEN 1 END) > 0 
                 AND COUNT(CASE WHEN processing_started_at IS NOT NULL THEN 1 END) > 0 
                 THEN 'Processing'
            WHEN COUNT(CASE WHEN claim_status = 'submitted' THEN 1 END) > 0 
                 AND COUNT(CASE WHEN processing_started_at IS NOT NULL THEN 1 END) = 0 
                 THEN 'Submitted'
            WHEN COUNT(CASE WHEN claim_status = 'processed' THEN 1 END) = COUNT(*) 
                 AND COUNT(CASE WHEN processed_status IN ('flagged', 'rejected') THEN 1 END) > 0 
                 THEN 'Under review'
            WHEN COUNT(CASE WHEN claim_status = 'processed' THEN 1 END) = COUNT(*) 
                 THEN 'Completed'
            ELSE 'Processing'
        END as processing_status,
        MAX(provider_name) as provider_name
    FROM claims_v3
    WHERE batch_id IS NOT NULL 
    GROUP BY batch_id
    HAVING (
        MIN(processing_started_at) IS NOT NULL 
        OR MAX(processing_completed_at) > NOW() - INTERVAL '2 hours'
        OR COUNT(CASE WHEN claim_status = 'submitted' THEN 1 END) > 0
    )
    ORDER BY MAX(COALESCE(processing_started_at, updated_at)) DESC
    """
    
    result = await queries.db.fetch_all(query)
    batches = []
    
    for row in result:
        percentage = (row['processed_claims'] / row['total_claims'] * 100) if row['total_claims'] > 0 else 0

        batches.append({
            "batch_id": row['batch_id'],
            "provider_name": row['provider_name'] or 'Unknown Provider',
            "processing_status": row['processing_status'],
            "total_claims": row['total_claims'],
            "processed_claims": row['processed_claims'],
            "approved_claims": row['approved_claims'],
            "rejected_claims": row['rejected_claims'],
            "flagged_claims": row['flagged_claims'],
            "pending_claims": row['pending_claims'],
            "percentage_complete": round(percentage, 1),
            "status": row['processing_status'].lower().replace(' ', '_'),
            "started_at": row['started_at'],
            "completed_at": row['completed_at'],
            "last_updated": row['last_updated']
        })
    
    return batches

async def broadcast_claim_processed(claim_update: ClaimProgressUpdate):
    await manager.send_to_batch_subscribers(claim_update.batch_id, {
        "type": "claim_processed",
        "data": claim_update.dict()
    })

async def broadcast_batch_progress_update(batch_id: str, queries):
    progress = await get_batch_progress(batch_id, queries)
    await manager.send_to_batch_subscribers(batch_id, {
        "type": "batch_progress",
        "data": progress.dict()
    })

async def broadcast_batch_completed(batch_id: str):
    await manager.send_to_batch_subscribers(batch_id, {
        "type": "batch_completed",
        "data": {"batch_id": batch_id, "status": "completed"}
    })

@router.post("/start-monitoring")
async def start_batch_monitoring(background_tasks: BackgroundTasks):
    global monitoring_active
    if monitoring_active:
        return {"message": "Batch monitoring already running"}
    
    monitoring_active = True
    background_tasks.add_task(monitor_all_batches_task)
    return {"message": "Batch monitoring started"}

@router.post("/trigger-update")
async def trigger_websocket_update(payload: dict):
    """Trigger immediate WebSocket update when database is updated"""
    try:
        encounter_id = payload.get("encounter_id")
        batch_id = payload.get("batch_id")
        status = payload.get("status")
        processed_status = payload.get("processed_status")
        
        logger.info(f"🔄 Manual trigger received for {encounter_id} (batch: {batch_id}, status: {status})")
        
        if batch_id:
            claim_update = ClaimProgressUpdate(
                encounter_id=encounter_id,
                batch_id=batch_id,
                old_status="processing",
                new_status=processed_status or status,
                processed_by="NHIS_EXPERT_SYSTEM",
                processing_stage="completed",
                updated_at=datetime.now()
            )
            await broadcast_claim_processed(claim_update)
            
            queries = await get_nhis_queries()
            await broadcast_batch_progress_update(batch_id, queries)
            
            logger.info(f"✅ WebSocket updates sent for {encounter_id}")
            return {"status": "success", "message": f"Updates sent for {encounter_id}"}
        else:
            logger.warning(f"⚠️ No batch_id provided for {encounter_id}")
            return {"status": "warning", "message": "No batch_id provided"}
            
    except Exception as e:
        logger.error(f"❌ Error triggering WebSocket update: {e}")
        return {"status": "error", "message": str(e)}

async def monitor_all_batches_task():
    """Background task for monitoring all batches"""
    global monitoring_active
    logger.info("Starting batch monitoring task...")
    
    while monitoring_active:
        try:
            queries = await get_nhis_queries()
            active_batches = await get_all_active_batches(queries)
            
            if manager.active_connections:
                await manager.broadcast_to_all({
                    "type": "all_batches_update",
                    "data": active_batches
                })
                logger.debug(f"Broadcasted update to {len(manager.active_connections)} connections")
            
            await asyncio.sleep(10)
            
        except Exception as e:
            logger.error(f"Error in batch monitoring task: {e}")
            await asyncio.sleep(30)
            
    logger.info("Batch monitoring task stopped")