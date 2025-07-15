#!/usr/bin/env python3
"""
Test script for Givebutter microservice
Tests all endpoints with proper authentication
"""

import os
import sys
import json
import asyncio
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.auth import impersonated_credentials
import httpx

# Configuration
MICROSERVICE_URL = "https://simple-givebutter-service-87276209817.us-central1.run.app"
SERVICE_ACCOUNT = "wlmn-givebutter-backend@wlmn-site-main.iam.gserviceaccount.com"

async def get_auth_token():
    """Get authentication token for Cloud Run service"""
    try:
        # Use Application Default Credentials
        from google.auth import default
        credentials, project = default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
        
        # Create impersonated credentials
        target_credentials = impersonated_credentials.Credentials(
            source_credentials=credentials,
            target_principal=SERVICE_ACCOUNT,
            target_scopes=['https://www.googleapis.com/auth/cloud-platform'],
            lifetime=3600
        )
        
        # Get identity token
        auth_req = Request()
        target_credentials.refresh(auth_req)
        
        # For Cloud Run, we need an identity token, not access token
        from google.auth.transport.requests import AuthorizedSession
        authed_session = AuthorizedSession(target_credentials)
        
        # Get identity token for the audience
        from google.auth import compute_engine
        from google.oauth2 import id_token
        
        request = Request()
        token = id_token.fetch_id_token(request, MICROSERVICE_URL)
        
        return token
    except Exception as e:
        print(f"❌ Failed to get auth token: {e}")
        return None

async def test_endpoint(endpoint: str, method: str = "GET", data: dict = None):
    """Test a microservice endpoint"""
    try:
        token = await get_auth_token()
        if not token:
            print(f"❌ No auth token available for {endpoint}")
            return
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient() as client:
            if method == "GET":
                response = await client.get(f"{MICROSERVICE_URL}{endpoint}", headers=headers)
            else:
                response = await client.post(f"{MICROSERVICE_URL}{endpoint}", headers=headers, json=data)
            
            print(f"\n📋 Testing {method} {endpoint}")
            print(f"Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Success!")
                print(json.dumps(data, indent=2))
            else:
                print(f"❌ Failed: {response.text}")
                
    except Exception as e:
        print(f"❌ Error testing {endpoint}: {e}")

async def main():
    """Run all tests"""
    print("🧪 Testing Givebutter Microservice")
    print("=" * 50)
    
    # Test health endpoint (no auth)
    print("\n📋 Testing GET /health (no auth)")
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{MICROSERVICE_URL}/health")
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            print("✅ Success!")
            print(json.dumps(response.json(), indent=2))
    
    # Test authenticated endpoints
    await test_endpoint("/api/donor-wall/summary")
    await test_endpoint("/api/donor-wall/sync-status")
    await test_endpoint("/api/donor-wall/data?limit=10")
    
    # Test sync trigger
    print("\n🔄 Triggering sync...")
    await test_endpoint("/api/donor-wall/sync", method="POST", data={"force_refresh": True})
    
    print("\n✅ All tests complete!")

if __name__ == "__main__":
    asyncio.run(main())