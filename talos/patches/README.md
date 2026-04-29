# Talos Patching

This directory contains Kustomization patches that are added to the talhelper configuration file.

<https://www.talos.dev/v1.7/talos-guides/configuration/patching/>

## Patch Directories

Under this `patches` directory, there are several sub-directories that can contain patches that are added to the talhelper configuration file.
Each directory is optional and therefore might not created by default.

- `global/`: patches that are applied to both the controller and worker configurations
- `controller/`: patches that are applied to the controller configurations
- `worker/`: patches that are applied to the worker configurations
- `${node-hostname}/`: patches that are applied to the node with the specified name

## Hardening Stance (homelab)

This cluster deliberately trades security for performance. Threat model: trusted
LAN, no PHI/PCI/sensitive workloads, single operator, physical access restricted.
The settings below are **not** appropriate for any cluster hosting external or
regulated workloads — flip them back to defaults before repurposing this stack.

| Setting | Value | Why |
|---|---|---|
| `machineSpec.secureboot` | `false` | Factory installer image not signed; avoids extra UEFI setup for a homelab. |
| `mitigations=off` | kernel arg | Disables Spectre/Meltdown mitigations. ~5–15% perf recovery on Zen2/Zen3. |
| `security=none` | kernel arg | Skips LSM stack init. |
| `apparmor=0` | kernel arg | No AppArmor profiles enforced. |
| `init_on_alloc=0` / `init_on_free=0` | kernel args | Skips kernel page zeroing — less heap-scrubbing overhead. |
| `talos.auditd.disabled=1` | kernel arg | Disables auditd to save CPU and log volume. |

If any of these need to be re-enabled for a specific workload:

1. Update `talos/patches/global/machine-kernel.yaml` (kernel args are managed here, **not** in `schematic.yaml`).
2. Run `task talos:generate-config` to regenerate per-node configs.
3. Roll through nodes with `task talos:apply-node IP=<ip>` and reboot.
