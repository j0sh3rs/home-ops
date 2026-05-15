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

## Schematic Hash Regeneration

`talos/talconfig.yaml` references the Talos Factory installer image by content
hash (`talosImageURL: factory.talos.dev/installer/<sha256>`). The hash is
derived deterministically from `talos/schematic.yaml` (extension list + kernel
args + meta values), so **any edit to `schematic.yaml` requires regenerating
the hash and updating `talconfig.yaml` in the same PR**, otherwise nodes
continue booting from the previous installer image and the schematic change
silently has no effect.

Renovate cannot bump these hashes — there is no datasource that maps schematic
content → installer hash. Manual workflow:

```bash
# 1. Edit talos/schematic.yaml as needed
# 2. POST the schematic to the Talos Factory and capture the returned hash
curl -sfX POST --data-binary @talos/schematic.yaml \
    https://factory.talos.dev/schematics
#    -> {"id":"<new-sha256-hash>"}
# 3. Replace every `talosImageURL: factory.talos.dev/installer/<old-hash>`
#    in talos/talconfig.yaml with the new hash.
# 4. task talos:generate-config
# 5. Roll through nodes one at a time (etcd quorum precheck applies):
#    task talos:upgrade-node IP=<ip>
```

Drift symptoms if you forget step 3: `talosctl --nodes <ip> get extensions`
won't show the new extension, `dmesg` lacks the new kernel args, and Talos
upgrade tasks happily report success because they're applying the *old*
installer image referenced in talconfig.

(Renovate-tracked: the **Talos version** itself in `talos/talenv.yaml`. That
bumps independently of schematic hash. A Talos minor version bump generally
does not require a schematic regen unless the Factory rebuilds extensions
incompatibly — rare.)
