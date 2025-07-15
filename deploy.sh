#!/bin/bash
set -e

# Configuration
PROJECT_ID="wlmn-site-main"
SERVICE_NAME="simple-givebutter-service"
REGION="us-central1"
IMAGE_NAME="gcr.io/$PROJECT_ID/$SERVICE_NAME"

echo "🚀 Deploying Givebutter Microservice to Google Cloud Run"
echo "=================================================="

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo "❌ gcloud CLI is not installed. Please install it first."
    exit 1
fi

# Check if authenticated
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" &> /dev/null; then
    echo "❌ Not authenticated with gcloud. Please run: gcloud auth login"
    exit 1
fi

# Set project
echo "📋 Setting project to $PROJECT_ID"
gcloud config set project $PROJECT_ID

# Enable required APIs
echo "🔧 Enabling required APIs..."
gcloud services enable run.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable containerregistry.googleapis.com
gcloud services enable secretmanager.googleapis.com

# Build the container
echo "🏗️  Building container image..."
gcloud builds submit --tag $IMAGE_NAME .

# Deploy to Cloud Run
echo "🚀 Deploying to Cloud Run..."
gcloud run deploy $SERVICE_NAME \
    --image $IMAGE_NAME \
    --region $REGION \
    --platform managed \
    --no-allow-unauthenticated \
    --service-account wlmn-givebutter-backend@$PROJECT_ID.iam.gserviceaccount.com \
    --set-env-vars PROJECT_ID=$PROJECT_ID,STORAGE_BUCKET=wlmn-site-main-assets,ENVIRONMENT=production \
    --set-secrets GIVEBUTTER_API_KEY=givebutter-api-key:latest \
    --memory 512Mi \
    --cpu 1 \
    --timeout 300 \
    --concurrency 100 \
    --max-instances 10

# Set IAM policy
echo "🔐 Setting IAM policy..."
gcloud run services add-iam-policy-binding $SERVICE_NAME \
    --region=$REGION \
    --member="serviceAccount:wlmn-backend@$PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/run.invoker"

# Get service URL
SERVICE_URL=$(gcloud run services describe $SERVICE_NAME --region $REGION --format 'value(status.url)')
echo ""
echo "✅ Deployment complete!"
echo "🌐 Service URL: $SERVICE_URL"
echo ""
echo "📝 Next steps:"
echo "1. Create the Givebutter API key secret if not exists:"
echo "   echo -n 'YOUR_API_KEY' | gcloud secrets create givebutter-api-key --data-file=-"
echo "2. Test the health endpoint:"
echo "   curl $SERVICE_URL/health"