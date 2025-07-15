"""
Simple Givebutter Microservice
Following Google Cloud Run authentication best practices

This microservice:
1. Accepts ONLY Google Cloud Run identity tokens (no custom JWT)
2. Validates tokens using Google's auth library
3. Polls Givebutter API for contacts, transactions, campaigns, plans
4. Stores data safely in Google Cloud Storage
5. Provides donor wall data endpoints
6. Updates data no more than every 15 minutes
"""

import os
import json
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional

from fastapi import FastAPI, HTTPException, Depends, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from google.auth.transport import requests
from google.oauth2 import id_token
from google.cloud import storage
import httpx
import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
PROJECT_ID = os.getenv('PROJECT_ID', 'wlmn-site-main')
STORAGE_BUCKET = os.getenv('STORAGE_BUCKET', 'wlmn-site-main-assets')
GIVEBUTTER_API_URL = os.getenv('GIVEBUTTER_API_URL', 'https://api.givebutter.com/v1')
GIVEBUTTER_API_KEY = os.getenv('GIVEBUTTER_API_KEY')
SYNC_INTERVAL_MINUTES = int(os.getenv('SYNC_INTERVAL_MINUTES', '15'))
ENVIRONMENT = os.getenv('ENVIRONMENT', 'development')

# Global state
app = FastAPI(title="Simple Givebutter Microservice", version="1.0.0")
storage_client = None
scheduler = None
last_sync_time = None
sync_status = "idle"

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AuthenticationError(Exception):
    pass

async def verify_google_identity_token(request: Request) -> Dict[str, Any]:
    """
    Verify Google Cloud Run identity token
    Following Google's best practices for service-to-service authentication
    """
    if ENVIRONMENT == 'development':
        # Skip authentication in development
        logger.info("🔧 Development mode: Skipping authentication")
        return {"email": "dev@localhost", "sub": "dev"}
    
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        raise AuthenticationError("Missing or invalid Authorization header")
    
    token = auth_header.split(' ', 1)[1]
    
    try:
        # Verify the token using Google's library
        # For Cloud Run, the audience should be the service URL
        audience = "https://simple-givebutter-service-87276209817.us-central1.run.app"
        decoded_token = id_token.verify_oauth2_token(
            token, 
            requests.Request(),
            audience=audience
        )
        
        logger.info(f"✅ Token verified for: {decoded_token.get('email')}")
        return decoded_token
        
    except Exception as e:
        logger.error(f"❌ Token verification failed: {e}")
        raise AuthenticationError(f"Invalid token: {e}")

async def get_authenticated_user(request: Request) -> Dict[str, Any]:
    """Dependency to get authenticated user"""
    try:
        return await verify_google_identity_token(request)
    except AuthenticationError as e:
        raise HTTPException(status_code=401, detail=str(e))

def get_storage_client():
    """Get Google Cloud Storage client"""
    global storage_client
    if storage_client is None:
        storage_client = storage.Client(project=PROJECT_ID)
    return storage_client

def get_bucket():
    """Get storage bucket"""
    client = get_storage_client()
    return client.bucket(STORAGE_BUCKET)

async def store_data_in_gcs(data_type: str, data: Dict[str, Any], integration_id: str = "default"):
    """Store data in Google Cloud Storage"""
    try:
        bucket = get_bucket()
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Structure: /givebutter-data/{integration-id}/{type}/{date}/data.json
        blob_path = f"givebutter-data/{integration_id}/{data_type}/{timestamp}/data.json"
        blob = bucket.blob(blob_path)
        
        blob.upload_from_string(
            json.dumps(data, indent=2),
            content_type='application/json'
        )
        
        logger.info(f"✅ Stored {data_type} data in GCS: {blob_path}")
        return blob_path
        
    except Exception as e:
        logger.error(f"❌ Failed to store {data_type} data in GCS: {e}")
        raise

async def get_latest_data_from_gcs(data_type: str, integration_id: str = "default") -> Optional[Dict[str, Any]]:
    """Get latest data from Google Cloud Storage"""
    try:
        bucket = get_bucket()
        
        # Handle wlmn-donor-data bucket with different structure
        if STORAGE_BUCKET == 'wlmn-donor-data':
            # Real data is stored in donor-data/latest.json
            try:
                blob = bucket.blob('donor-data/latest.json')
                if blob.exists():
                    data = json.loads(blob.download_as_text())
                    logger.info(f"✅ Retrieved real donor data from wlmn-donor-data bucket")
                    
                    # Transform the data structure to match expected format
                    if data_type == 'summary':
                        return {
                            "total_donors": data.get('total_donors', 0),
                            "total_transactions": data.get('total_donations', 0),
                            "total_amount_cents": int(data.get('total_amount', 0) * 100),
                            "total_amount_dollars": data.get('total_amount', 0),
                            "active_recurring_plans": 0,  # Calculate from data if needed
                            "last_updated": data.get('last_sync'),
                            "sync_status": data.get('sync_status', 'success')
                        }
                    elif data_type == 'contacts':
                        # Return the contacts array directly
                        contacts = data.get('contacts', [])
                        return {"data": contacts} if isinstance(contacts, list) else contacts
                    elif data_type == 'transactions':
                        # Return the transactions array directly  
                        transactions = data.get('transactions', [])
                        return {"data": transactions} if isinstance(transactions, list) else transactions
                    else:
                        return data
                else:
                    logger.warning(f"Real donor data file not found in wlmn-donor-data bucket")
                    return None
            except Exception as e:
                logger.error(f"Failed to read real donor data: {e}")
                return None
        else:
            # Original logic for wlmn-site-main-assets bucket (test data)
            prefix = f"givebutter-data/{integration_id}/{data_type}/"
            
            # Get all blobs with this prefix, sorted by name (timestamp)
            blobs = list(bucket.list_blobs(prefix=prefix))
            if not blobs:
                return None
                
            # Get the most recent blob
            latest_blob = max(blobs, key=lambda b: b.name)
            data = json.loads(latest_blob.download_as_text())
            
            logger.info(f"✅ Retrieved {data_type} data from GCS: {latest_blob.name}")
            return data
        
    except Exception as e:
        logger.error(f"❌ Failed to retrieve {data_type} data from GCS: {e}")
        return None

async def poll_givebutter_api(endpoint: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
    """Poll Givebutter API endpoint"""
    if not GIVEBUTTER_API_KEY:
        logger.warning("⚠️ GIVEBUTTER_API_KEY not set, using mock data")
        return generate_mock_data(endpoint)
    
    try:
        headers = {
            'Authorization': f'Bearer {GIVEBUTTER_API_KEY}',
            'Content-Type': 'application/json'
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{GIVEBUTTER_API_URL}/{endpoint}",
                headers=headers,
                params=params or {},
                timeout=30.0
            )
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"✅ Successfully polled Givebutter API: {endpoint}")
            return data
            
    except Exception as e:
        logger.error(f"❌ Failed to poll Givebutter API {endpoint}: {e}")
        # Return mock data as fallback
        return generate_mock_data(endpoint)

def generate_mock_data(endpoint: str) -> Dict[str, Any]:
    """Generate mock data for development/testing"""
    now = datetime.now(timezone.utc).isoformat()
    
    if 'contacts' in endpoint:
        return {
            "data": [
                {
                    "id": "contact_123",
                    "first_name": "John",
                    "last_name": "Doe",
                    "email": "john.doe@example.com",
                    "phone": "+1234567890",
                    "total_donated": 50000,  # $500.00 in cents
                    "donation_count": 5,
                    "created_at": now
                }
            ],
            "meta": {"total": 1, "page": 1, "per_page": 100}
        }
    elif 'transactions' in endpoint:
        return {
            "data": [
                {
                    "id": "txn_456",
                    "amount": 10000,  # $100.00 in cents
                    "fee": 329,  # $3.29 in cents
                    "net_amount": 9671,
                    "status": "succeeded",
                    "method": "card",
                    "contact_id": "contact_123",
                    "campaign_id": "campaign_789",
                    "created_at": now
                }
            ],
            "meta": {"total": 1, "page": 1, "per_page": 100}
        }
    elif 'plans' in endpoint:
        return {
            "data": [
                {
                    "id": "plan_789",
                    "amount": 2500,  # $25.00 in cents
                    "interval": "monthly",
                    "status": "active",
                    "contact_id": "contact_123",
                    "created_at": now
                }
            ],
            "meta": {"total": 1, "page": 1, "per_page": 100}
        }
    elif 'campaigns' in endpoint:
        return {
            "data": [
                {
                    "id": "campaign_789",
                    "title": "Annual Fundraiser",
                    "goal": 1000000,  # $10,000.00 in cents
                    "raised": 750000,  # $7,500.00 in cents
                    "status": "active",
                    "created_at": now
                }
            ],
            "meta": {"total": 1, "page": 1, "per_page": 100}
        }
    
    return {"data": [], "meta": {"total": 0, "page": 1, "per_page": 100}}

async def sync_all_data():
    """Sync all data from Givebutter API to Google Cloud Storage"""
    global sync_status, last_sync_time
    
    if sync_status == "syncing":
        logger.info("⏳ Sync already in progress, skipping")
        return
    
    sync_status = "syncing"
    logger.info("🔄 Starting data sync...")
    
    try:
        # Poll all data types
        data_types = ['contacts', 'transactions', 'plans', 'campaigns']
        
        for data_type in data_types:
            logger.info(f"📥 Syncing {data_type}...")
            data = await poll_givebutter_api(data_type)
            await store_data_in_gcs(data_type, data)
        
        # Generate aggregated summary
        await generate_donor_summary()
        
        last_sync_time = datetime.now(timezone.utc)
        sync_status = "completed"
        logger.info("✅ Data sync completed successfully")
        
    except Exception as e:
        sync_status = "failed"
        logger.error(f"❌ Data sync failed: {e}")
        raise

async def generate_donor_summary():
    """Generate aggregated donor summary data"""
    try:
        # Get latest data for all types
        contacts_data = await get_latest_data_from_gcs('contacts')
        transactions_data = await get_latest_data_from_gcs('transactions')
        plans_data = await get_latest_data_from_gcs('plans')
        campaigns_data = await get_latest_data_from_gcs('campaigns')
        
        # Calculate summary statistics
        total_donors = len(contacts_data.get('data', [])) if contacts_data else 0
        total_transactions = len(transactions_data.get('data', [])) if transactions_data else 0
        total_amount = sum(txn.get('amount', 0) for txn in transactions_data.get('data', [])) if transactions_data else 0
        active_plans = len([p for p in plans_data.get('data', []) if p.get('status') == 'active']) if plans_data else 0
        
        summary = {
            "total_donors": total_donors,
            "total_transactions": total_transactions,
            "total_amount_cents": total_amount,
            "total_amount_dollars": total_amount / 100,
            "active_recurring_plans": active_plans,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "sync_status": sync_status
        }
        
        # Store summary
        await store_data_in_gcs('summary', summary)
        logger.info("✅ Generated donor summary")
        
    except Exception as e:
        logger.error(f"❌ Failed to generate donor summary: {e}")

# API Endpoints

@app.get("/health")
async def health_check():
    """Health check endpoint - no authentication required"""
    return {
        "status": "healthy",
        "service": "simple-givebutter-microservice",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "last_sync": last_sync_time.isoformat() if last_sync_time else None,
        "sync_status": sync_status
    }

@app.get("/api/donor-wall/summary")
async def get_donor_summary(user: Dict[str, Any] = Depends(get_authenticated_user)):
    """Get aggregated donor summary statistics"""
    try:
        summary_data = await get_latest_data_from_gcs('summary')
        
        if not summary_data:
            # Generate summary if not exists
            await generate_donor_summary()
            summary_data = await get_latest_data_from_gcs('summary')
        
        return {
            "success": True,
            "data": summary_data or {
                "total_donors": 0,
                "total_transactions": 0,
                "total_amount_cents": 0,
                "total_amount_dollars": 0,
                "active_recurring_plans": 0,
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "sync_status": sync_status
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to get donor summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/donor-wall/data")
async def get_donor_data(
    limit: int = 100,
    offset: int = 0,
    user: Dict[str, Any] = Depends(get_authenticated_user)
):
    """Get paginated donor data"""
    try:
        contacts_data = await get_latest_data_from_gcs('contacts')
        transactions_data = await get_latest_data_from_gcs('transactions')
        
        if not contacts_data:
            return {
                "success": True,
                "data": [],
                "meta": {
                    "total": 0,
                    "page": offset // limit + 1,
                    "per_page": limit,
                    "has_more": False
                },
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        
        # Combine contact and transaction data
        contacts = contacts_data.get('data', [])
        transactions = transactions_data.get('data', []) if transactions_data else []
        
        # Create transaction lookup by contact_id
        contact_transactions = {}
        for txn in transactions:
            contact_id = txn.get('contact_id')
            if contact_id:
                if contact_id not in contact_transactions:
                    contact_transactions[contact_id] = []
                contact_transactions[contact_id].append(txn)
        
        # Enrich contacts with transaction data
        enriched_contacts = []
        for contact in contacts:
            contact_id = contact.get('id')
            contact_txns = contact_transactions.get(contact_id, [])
            
            enriched_contact = {
                **contact,
                "transactions": contact_txns,
                "transaction_count": len(contact_txns),
                "total_donated_calculated": sum(txn.get('amount', 0) for txn in contact_txns)
            }
            enriched_contacts.append(enriched_contact)
        
        # Apply pagination
        total = len(enriched_contacts)
        paginated_data = enriched_contacts[offset:offset + limit]
        
        return {
            "success": True,
            "data": paginated_data,
            "meta": {
                "total": total,
                "page": offset // limit + 1,
                "per_page": limit,
                "has_more": offset + limit < total
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to get donor data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/donor-wall/sync")
async def trigger_manual_sync(
    background_tasks: BackgroundTasks,
    user: Dict[str, Any] = Depends(get_authenticated_user)
):
    """Trigger manual data sync"""
    try:
        if sync_status == "syncing":
            return {
                "success": False,
                "message": "Sync already in progress",
                "status": sync_status,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        
        # Trigger sync in background
        background_tasks.add_task(sync_all_data)
        
        return {
            "success": True,
            "message": "Manual sync triggered",
            "status": "syncing",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to trigger manual sync: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/donor-wall/sync-status")
async def get_sync_status(user: Dict[str, Any] = Depends(get_authenticated_user)):
    """Get current sync status"""
    return {
        "success": True,
        "data": {
            "status": sync_status,
            "last_sync": last_sync_time.isoformat() if last_sync_time else None,
            "next_sync": (last_sync_time + timedelta(minutes=SYNC_INTERVAL_MINUTES)).isoformat() if last_sync_time else None
        },
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.on_event("startup")
async def startup_event():
    """Initialize the application"""
    global scheduler
    
    logger.info("🚀 Starting Simple Givebutter Microservice...")
    
    # Initialize Google Cloud Storage
    try:
        get_storage_client()
        logger.info("✅ Google Cloud Storage initialized")
    except Exception as e:
        logger.error(f"❌ Failed to initialize Google Cloud Storage: {e}")
    
    # Initialize scheduler for periodic sync
    scheduler = AsyncIOScheduler()
    
    # Add sync job (every SYNC_INTERVAL_MINUTES minutes)
    scheduler.add_job(
        sync_all_data,
        trigger=IntervalTrigger(minutes=SYNC_INTERVAL_MINUTES),
        id='sync_givebutter_data',
        replace_existing=True
    )
    
    scheduler.start()
    logger.info(f"✅ Scheduler started - syncing every {SYNC_INTERVAL_MINUTES} minutes")
    
    # Perform initial sync
    try:
        await sync_all_data()
        logger.info("✅ Initial data sync completed")
    except Exception as e:
        logger.error(f"❌ Initial data sync failed: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    global scheduler
    
    logger.info("🛑 Shutting down Simple Givebutter Microservice...")
    
    if scheduler:
        scheduler.shutdown()
        logger.info("✅ Scheduler shut down")

if __name__ == "__main__":
    # Run the application
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=ENVIRONMENT == "development"
    ) 