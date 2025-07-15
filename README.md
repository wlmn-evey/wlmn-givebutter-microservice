# Givebutter Donor Sync Microservice

A secure, scalable microservice for syncing donor data from Givebutter API to Google Cloud Storage. Built with FastAPI and deployed on Google Cloud Run.

## Features

- 🔐 Secure authentication using Google Cloud Run identity tokens
- 📊 Automatic syncing of donor data every 15 minutes
- 💾 Data storage in Google Cloud Storage with versioning
- 🚀 Fast API endpoints for donor statistics and data retrieval
- 📈 Automatic aggregation of donor metrics
- 🔄 Manual sync triggering capability
- 🏃 Zero-downtime deployments with Cloud Run

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   WLMN Backend  │────▶│  This Microservice│────▶│  Givebutter API │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │
                               ▼
                        ┌──────────────────┐
                        │  Google Cloud    │
                        │     Storage      │
                        └──────────────────┘
```

## API Endpoints

- `GET /health` - Health check (no auth required)
- `GET /api/donor-wall/summary` - Get aggregated donor statistics
- `GET /api/donor-wall/data` - Get paginated donor data
- `POST /api/donor-wall/sync` - Trigger manual data sync
- `GET /api/donor-wall/sync-status` - Check sync status

## Development

### Prerequisites

- Python 3.11+
- Google Cloud SDK
- Givebutter API key
- Google Cloud project with Cloud Run and Cloud Storage enabled

### Local Development

1. Clone the repository:
```bash
git clone https://github.com/YOUR_ORG/givebutter-microservice.git
cd givebutter-microservice
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set environment variables:
```bash
export PROJECT_ID=your-gcp-project
export STORAGE_BUCKET=your-storage-bucket
export GIVEBUTTER_API_KEY=your-api-key
export ENVIRONMENT=development
```

5. Run the service:
```bash
python main.py
```

The service will be available at http://localhost:8080

### Testing

Run the test suite:
```bash
pytest tests/
```

## Deployment

### Automatic Deployment (GitHub Actions)

The service is automatically deployed to Google Cloud Run on every push to the `main` branch using GitHub Actions.

### Manual Deployment

1. Build the container:
```bash
gcloud builds submit --tag gcr.io/PROJECT_ID/givebutter-microservice
```

2. Deploy to Cloud Run:
```bash
gcloud run deploy givebutter-microservice \
  --image gcr.io/PROJECT_ID/givebutter-microservice \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars PROJECT_ID=PROJECT_ID,STORAGE_BUCKET=BUCKET_NAME
```

## Configuration

### Environment Variables

- `PROJECT_ID` - Google Cloud project ID
- `STORAGE_BUCKET` - Google Cloud Storage bucket name
- `GIVEBUTTER_API_KEY` - Givebutter API key (stored in Secret Manager)
- `SYNC_INTERVAL_MINUTES` - Data sync interval (default: 15)
- `ENVIRONMENT` - Environment name (development/production)

### Service Account Permissions

The service account needs the following roles:
- `roles/storage.objectAdmin` - For Cloud Storage operations
- `roles/logging.logWriter` - For logging
- `roles/cloudtrace.agent` - For tracing (optional)

## Monitoring

- View logs: `gcloud run services logs read givebutter-microservice`
- View metrics in Cloud Console: [Cloud Run Metrics](https://console.cloud.google.com/run)
- Set up alerts for sync failures in Cloud Monitoring

## Security

- All endpoints (except health) require Google Cloud Run identity tokens
- API keys are stored in Google Secret Manager
- Service runs as non-root user in container
- Automatic security scanning via GitHub Actions

## License

[Your License]