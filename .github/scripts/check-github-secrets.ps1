# Check if all required GitHub Secrets are configured
# Usage: .\check-github-secrets.ps1

param(
    [string]$Repo = ""
)

# Required secrets
$RequiredSecrets = @(
    "DATABASE_URL",
    "SECRET_KEY",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "SENDGRID_API_KEY",
    "ALLOWED_ORIGINS",
    "MZONE_CLIENT_ID",
    "MZONE_CLIENT_SECRET",
    "MZONE_USERNAME",
    "MZONE_PASSWORD",
    "DO_SSH_PRIVATE_KEY",
    "DO_SERVER_IP",
    "DO_USER"
)

Write-Host "🔍 Checking GitHub Secrets..." -ForegroundColor Cyan
Write-Host ""

# Check if gh CLI is installed
$ghPath = Get-Command gh -ErrorAction SilentlyContinue
if (-not $ghPath) {
    Write-Host "⚠️  GitHub CLI not installed." -ForegroundColor Yellow
    Write-Host "   Install from: https://cli.github.com"
    Write-Host "   Then run: gh auth login"
    exit 1
}

# Get current repo
if ([string]::IsNullOrEmpty($Repo)) {
    $Repo = & gh repo view --json nameWithOwner -q 2>$null
    if ($LASTEXITCODE -ne 0) {
        $Repo = "unknown"
    }
}

Write-Host "Repository: $Repo" -ForegroundColor Gray
Write-Host ""

# Get list of all secrets
Write-Host "Fetching secrets from GitHub..." -ForegroundColor Gray
$Secrets = & gh secret list --json name -q 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Could not fetch secrets. Make sure you're authenticated:" -ForegroundColor Red
    Write-Host "   gh auth login"
    exit 1
}

# Parse secrets into array
$SecretNames = $Secrets -split "`n" | Where-Object { $_ -match '\S' }

# Check each required secret
$Missing = 0
Write-Host "Checking required secrets:" -ForegroundColor Cyan
Write-Host "────────────────────────────────────────"

foreach ($Secret in $RequiredSecrets) {
    if ($SecretNames -contains $Secret) {
        # Try to get secret length
        $SecretValue = & gh secret view $Secret 2>$null
        if ($LASTEXITCODE -eq 0 -and $SecretValue) {
            $Length = $SecretValue.Length
            Write-Host "✅ $Secret ($($Length) chars)" -ForegroundColor Green
        } else {
            Write-Host "⚠️  $Secret (empty value)" -ForegroundColor Yellow
            $Missing++
        }
    } else {
        Write-Host "❌ $Secret (MISSING)" -ForegroundColor Red
        $Missing++
    }
}

Write-Host "────────────────────────────────────────"
Write-Host ""

if ($Missing -gt 0) {
    Write-Host "❌ DEPLOYMENT WILL FAIL" -ForegroundColor Red
    Write-Host ""
    Write-Host "Missing or empty secrets: $Missing" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "To add a secret:" -ForegroundColor Cyan
    Write-Host "  1. Go to: GitHub Repo → Settings → Secrets and variables → Actions"
    Write-Host "  2. Click 'New repository secret'"
    Write-Host "  3. Name: (secret name from above)"
    Write-Host "  4. Value: (paste the value)"
    Write-Host "  5. Click 'Add secret'"
    Write-Host ""
    Write-Host "Or use GitHub CLI:" -ForegroundColor Cyan
    Write-Host "  gh secret set SECRET_NAME --body 'secret_value'"
    Write-Host ""
    exit 1
} else {
    Write-Host "✅ ALL SECRETS CONFIGURED" -ForegroundColor Green
    Write-Host ""
    Write-Host "Ready for deployment!" -ForegroundColor Green
    exit 0
}
