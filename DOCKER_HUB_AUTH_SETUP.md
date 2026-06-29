# Docker Hub Authentication Setup (Increases Rate Limit)

## Problem
- Unauthenticated: 100 pulls / 6 hours
- Authenticated: 200 pulls / 6 hours (free account)
- Pro account: 5,000 pulls / day

## Quick Setup (5 minutes)

### Step 1: Create Docker Hub Access Token
1. Go to https://hub.docker.com/settings/security
2. Click "New Access Token"
3. Name: `github-actions-pinplot`
4. Permissions: `Read-only`
5. Click "Generate"
6. **Copy the token immediately** (you won't see it again)

### Step 2: Add GitHub Secrets
1. Go to https://github.com/PinPlot/PinPlot-HPS/settings/secrets/actions
2. Click "New repository secret"
3. Add two secrets:
   - Name: `DOCKERHUB_USERNAME`
     Value: (your Docker Hub username)
   - Name: `DOCKERHUB_TOKEN`  
     Value: (the token from Step 1)

### Step 3: Update Workflow (I'll do this if you choose this option)
Add login step before deployment:
```yaml
- name: Docker Hub Login
  uses: docker/login-action@v3
  with:
    username: ${{ secrets.DOCKERHUB_USERNAME }}
    password: ${{ secrets.DOCKERHUB_TOKEN }}
```

## When to Use This
- **If rate-limited now:** Gives immediate relief (200 vs 100 pulls)
- **Long-term:** Nice to have, but the new workflow fix means you'll rarely pull anyway
- **If you deploy >16 times per day:** Definitely add this

## Note
With the new workflow fix (prune without -a, --pull never), you should rarely hit limits anyway since base images are cached. This is just extra insurance.
