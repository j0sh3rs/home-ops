# Forgejo CI Runner Setup for Codeberg

Complete guide for deploying Forgejo CI runners to work with your Codeberg account (j0sh3rs).

## Prerequisites

- FluxCD GitOps cluster already configured
- SOPS with Age encryption configured
- `kubectl` access to the cluster with `home` context
- Access to Codeberg account: https://codeberg.org/j0sh3rs

## Step 1: Generate Runner Registration Token

1. **Navigate to Codeberg Repository Settings**:
   - Go to https://codeberg.org/j0sh3rs (or your specific repository)
   - Click on **Settings** (gear icon)
   - Navigate to **Actions** → **Runners**

2. **Create New Runner**:
   - Click **"Add new runner"** or **"Create runner token"**
   - Select runner type: **"Repository"** (or Organization/Global based on your needs)
   - **Copy the registration token** - you'll need this immediately (it's shown only once)
   - Token format: typically a long alphanumeric string like `ABC123DEF456GHI789JKL012MNO345PQR678`

## Step 2: Update the Encrypted Secret

The current secret has placeholder values that need to be replaced with your actual Codeberg token.

### Decrypt the Secret

```bash
cd /Users/josh.simmonds/Documents/github/j0sh3rs/home-ops

# Decrypt to temporary file
sops -d kubernetes/apps/ci/forgejo-runner/app/secret.sops.yaml > /tmp/forgejo-secret.yaml
```

### Edit the Decrypted Secret

Open `/tmp/forgejo-secret.yaml` in your editor:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: forgejo-runner-secret
type: Opaque
stringData:
  RUNNER_TOKEN: "PASTE_YOUR_CODEBERG_TOKEN_HERE"
  FORGEJO_INSTANCE_URL: "https://codeberg.org"
```

**Replace**:
- `PASTE_YOUR_CODEBERG_TOKEN_HERE` with the token you copied from Codeberg
- Verify `FORGEJO_INSTANCE_URL` is correct: `https://codeberg.org`

### Re-encrypt the Secret

```bash
# Re-encrypt the secret
sops -e /tmp/forgejo-secret.yaml > kubernetes/apps/ci/forgejo-runner/app/secret.sops.yaml

# Clean up temporary file
rm /tmp/forgejo-secret.yaml
```

## Step 3: Commit and Push Changes

```bash
cd /Users/josh.simmonds/Documents/github/j0sh3rs/home-ops

# Check what will be committed
git status

# Stage the encrypted secret
git add kubernetes/apps/ci/forgejo-runner/app/secret.sops.yaml
git add kubernetes/apps/ci/kustomization.yaml  # If not already committed

# Commit with descriptive message
git commit -m "feat(ci): configure Forgejo runner with Codeberg token"

# Push to trigger FluxCD reconciliation
git push origin main
```

## Step 4: Deploy via FluxCD

FluxCD will automatically detect the changes and reconcile. You can monitor the deployment:

```bash
# Watch FluxCD reconciliation
flux get kustomizations -A --watch

# Specifically watch ci namespace
flux reconcile kustomization ci -n flux-system --context home

# Watch pods coming up
kubectl get pods -n ci --watch --context home
```

**Expected Output**:
```
NAME                        READY   STATUS    RESTARTS   AGE
forgejo-runner-0            3/3     Running   0          2m
forgejo-runner-1            3/3     Running   0          2m
```

Each pod runs 3 containers:
- `runner-register` (InitContainer - completes after registration)
- `daemon` (Docker-in-Docker)
- `app` (Forgejo runner)

## Step 5: Verify Deployment

### Check Pod Status

```bash
# View pods
kubectl get pods -n ci --context home

# Check logs for registration
kubectl logs -n ci forgejo-runner-0 -c app --context home

# Check Docker daemon
kubectl logs -n ci forgejo-runner-0 -c daemon --context home
```

### Verify in Codeberg UI

1. Go to your Codeberg repository → **Settings** → **Actions** → **Runners**
2. You should see two active runners:
   - `forgejo-runner-forgejo-runner-0`
   - `forgejo-runner-forgejo-runner-1`
3. Status should show **"Idle"** (green) indicating they're connected and ready

### Test with Sample Workflow

Create a test workflow file in your Codeberg repository:

```yaml
# .forgejo/workflows/test.yml
name: Test Runner
on: [push]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Echo test
        run: echo "Forgejo runner is working!"

      - name: Docker test
        run: docker --version
```

Push this file and check Actions tab in Codeberg - the workflow should execute on your runners.

## Troubleshooting

### Runner Pods Not Starting

**Check pod events**:
```bash
kubectl describe pod -n ci forgejo-runner-0 --context home
```

**Common issues**:
- **Secret not decrypted**: Verify SOPS configuration in `.sops.yaml`
- **ImagePullBackOff**: Check internet connectivity and image repository access
- **CrashLoopBackOff**: Check logs for registration errors

### Registration Fails

**Check InitContainer logs**:
```bash
kubectl logs -n ci forgejo-runner-0 -c runner-register --context home
```

**Common causes**:
- **Invalid token**: Token may have expired or been used already - generate new token
- **Wrong URL**: Verify `FORGEJO_INSTANCE_URL` is `https://codeberg.org`
- **Network issues**: Check cluster can reach codeberg.org

### Docker Daemon Not Ready

**Check daemon logs**:
```bash
kubectl logs -n ci forgejo-runner-0 -c daemon --context home
```

**Check runner logs**:
```bash
kubectl logs -n ci forgejo-runner-0 -c app --context home
```

Look for: `"Waiting for Docker daemon..."` followed by `"Docker daemon ready, starting runner..."`

If stuck waiting, check:
- Privileged security context is allowed in your cluster
- Docker daemon has sufficient resources (memory: 256Mi-1Gi, cpu: 100m-500m)

### Runners Show as Offline in Codeberg

**Verify network connectivity**:
```bash
# Exec into runner pod
kubectl exec -it -n ci forgejo-runner-0 -c app --context home -- sh

# Test Codeberg connectivity
nc -zv codeberg.org 443
curl -I https://codeberg.org
```

**Check runner status**:
```bash
# View runner logs for connection errors
kubectl logs -n ci forgejo-runner-0 -c app --follow --context home
```

### Resource Constraints

If pods are evicted or OOMKilled:

**Check resource usage**:
```bash
kubectl top pods -n ci --context home
```

**Current limits per pod**: 2Gi memory + 1 CPU total
- daemon container: 1Gi memory, 500m CPU
- app container: 1Gi memory, 500m CPU

You can adjust in `kubernetes/apps/ci/forgejo-runner/app/helmrelease.yaml` under `resources.limits`.

## Configuration Reference

### Resource Limits (Per Pod)

Total per pod: **2Gi RAM + 1 CPU**
- Docker daemon: 1Gi RAM, 500m CPU (privileged)
- Runner app: 1Gi RAM, 500m CPU
- 2 replica pods = **4Gi RAM + 2 CPU total cluster usage**

### Runner Configuration

- **Replicas**: 2 (for high availability)
- **Strategy**: RollingUpdate
- **Labels**:
  - `docker:docker://ghcr.io/catthehacker/ubuntu:act-latest` (Docker executor)
  - `ubuntu-latest:host` (Host executor)

### Volumes

All volumes are `emptyDir` (ephemeral):
- `/data` - Runner config and registration
- `/certs` - Docker TLS certificates
- `/var/lib/docker` - Docker daemon storage

**Note**: Ephemeral storage means runners are stateless - perfect for CI workloads.

## Scaling Runners

To change the number of runners, edit `helmrelease.yaml`:

```yaml
controllers:
  forgejo-runner:
    replicas: 3  # Change this value
```

Commit, push, and let FluxCD reconcile.

## Security Considerations

1. **Privileged Containers**: Docker-in-Docker requires privileged mode - this is standard for CI runners
2. **Secret Management**: Runner token is encrypted with SOPS - never commit unencrypted
3. **Network Access**: Runners have outbound access to Codeberg and container registries
4. **Resource Limits**: Enforced to prevent resource exhaustion attacks
5. **Ephemeral Storage**: No persistent data - each run starts clean

## Additional Resources

- **Forgejo Actions Documentation**: https://forgejo.org/docs/latest/user/actions/
- **Forgejo Runner GitHub**: https://code.forgejo.org/forgejo/runner
- **bjw-s app-template Chart**: https://bjw-s.github.io/helm-charts/docs/app-template/
- **FluxCD Documentation**: https://fluxcd.io/flux/

## Quick Command Reference

```bash
# View runner pods
kubectl get pods -n ci --context home

# Follow runner logs
kubectl logs -n ci -l app.kubernetes.io/name=forgejo-runner -f --context home

# Force FluxCD reconciliation
flux reconcile kustomization ci -n flux-system --context home

# Restart runners (delete pods, they'll be recreated)
kubectl delete pods -n ci -l app.kubernetes.io/name=forgejo-runner --context home

# View runner resource usage
kubectl top pods -n ci --context home

# Edit runner configuration
kubectl edit helmrelease forgejo-runner -n ci --context home
# (Changes will be overwritten by FluxCD - edit Git instead)
```

## Support

For issues specific to:
- **Codeberg**: https://codeberg.org/Codeberg/Community/issues
- **Forgejo Runner**: https://code.forgejo.org/forgejo/runner/issues
- **FluxCD**: https://github.com/fluxcd/flux2/discussions
