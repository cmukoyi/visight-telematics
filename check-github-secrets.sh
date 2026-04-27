#!/bin/bash
# Check if all required GitHub Secrets are configured

set -e

# Required secrets
REQUIRED_SECRETS=(
  "DATABASE_URL"
  "SECRET_KEY"
  "POSTGRES_USER"
  "POSTGRES_PASSWORD"
  "POSTGRES_DB"
  "SENDGRID_API_KEY"
  "ALLOWED_ORIGINS"
  "MZONE_CLIENT_ID"
  "MZONE_CLIENT_SECRET"
  "MZONE_USERNAME"
  "MZONE_PASSWORD"
  "DO_SSH_PRIVATE_KEY"
  "DO_SERVER_IP"
  "DO_USER"
)

echo "🔍 Checking GitHub Secrets..."
echo ""

# Check if gh CLI is installed
if ! command -v gh &> /dev/null; then
  echo "⚠️  GitHub CLI not installed. Install with: brew install gh"
  echo "Then run: gh auth login"
  exit 1
fi

# Get current repo
REPO=$(gh repo view --json nameWithOwner -q 2>/dev/null || echo "unknown")
echo "Repository: $REPO"
echo ""

# Get list of all secrets
echo "Fetching secrets from GitHub..."
SECRETS=$(gh secret list --json name -q 2>/dev/null || echo "")

if [ -z "$SECRETS" ]; then
  echo "❌ Could not fetch secrets. Make sure you're authenticated:"
  echo "   gh auth login"
  exit 1
fi

# Check each required secret
MISSING=0
echo "Checking required secrets:"
echo "────────────────────────────────────────"

for SECRET in "${REQUIRED_SECRETS[@]}"; do
  if echo "$SECRETS" | grep -q "^$SECRET$"; then
    # Get the secret length to confirm it's not empty
    SECRET_VALUE=$(gh secret view $SECRET 2>/dev/null || echo "")
    if [ -n "$SECRET_VALUE" ]; then
      LENGTH=${#SECRET_VALUE}
      echo "✅ $SECRET (${LENGTH} chars)"
    else
      echo "⚠️  $SECRET (empty value)"
      MISSING=$((MISSING + 1))
    fi
  else
    echo "❌ $SECRET (MISSING)"
    MISSING=$((MISSING + 1))
  fi
done

echo "────────────────────────────────────────"
echo ""

if [ $MISSING -gt 0 ]; then
  echo "❌ DEPLOYMENT WILL FAIL"
  echo ""
  echo "Missing or empty secrets: $MISSING"
  echo ""
  echo "To add a secret:"
  echo "  1. Go to: GitHub Repo → Settings → Secrets and variables → Actions"
  echo "  2. Click 'New repository secret'"
  echo "  3. Name: (secret name from above)"
  echo "  4. Value: (paste the value)"
  echo "  5. Click 'Add secret'"
  echo ""
  echo "Or use GitHub CLI:"
  echo "  gh secret set SECRET_NAME --body 'secret_value'"
  echo ""
  exit 1
else
  echo "✅ ALL SECRETS CONFIGURED"
  echo ""
  echo "Ready for deployment!"
  exit 0
fi
