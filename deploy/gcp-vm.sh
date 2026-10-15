#!/bin/sh
# Deploy Relay to one Compute Engine VM running docker compose.
# Usage: PROJECT=my-gcp-project ./deploy/gcp-vm.sh
# Needs: gcloud CLI logged in (gcloud auth login), billing enabled on PROJECT.
set -eu
: "${PROJECT:?Set PROJECT to your Google Cloud project id}"
ZONE="${ZONE:-asia-south1-a}"
VM="${VM:-relay}"
cd "$(dirname "$0")/.."

gcloud config set project "$PROJECT"
gcloud services enable compute.googleapis.com aiplatform.googleapis.com

if ! gcloud compute instances describe "$VM" --zone "$ZONE" >/dev/null 2>&1; then
  gcloud compute instances create "$VM" --zone "$ZONE" --machine-type e2-standard-4 \
    --image-family debian-12 --image-project debian-cloud --boot-disk-size 40GB \
    --scopes cloud-platform --tags relay-web \
    --metadata startup-script='#!/bin/sh
      command -v docker >/dev/null || (curl -fsSL https://get.docker.com | sh)'
  gcloud compute firewall-rules create relay-web --allow tcp:80 --target-tags relay-web 2>/dev/null || true
  echo "Waiting for Docker to install on the VM…"; sleep 90
fi

# Ship the code (without node_modules and the unused Kestra clone) and the .env.
tar --exclude node_modules --exclude kestra --exclude .git --exclude web/dist -czf /tmp/relay.tgz .
gcloud compute scp /tmp/relay.tgz "$VM":~/relay.tgz --zone "$ZONE"
gcloud compute ssh "$VM" --zone "$ZONE" --command '
  mkdir -p relay && tar -xzf relay.tgz -C relay && cd relay &&
  sudo WEB_PORT=80 docker compose up -d --build'
IP=$(gcloud compute instances describe "$VM" --zone "$ZONE" --format='get(networkInterfaces[0].accessConfigs[0].natIP)')
echo "Relay is starting at http://$IP (first boot takes a few minutes)."
