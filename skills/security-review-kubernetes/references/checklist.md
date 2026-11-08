# Kubernetes artifact checklist

One row per check, run against the **rendered** YAML and mapped back to the source
`file:line`. **Freq** = how often it shows up in real repos; **Impact** = how bad when it
holds and nothing else mitigates. Score them separately (freq → `confidence`, impact →
`severity`). **Static** = checkable from the artifacts alone: YES, PARTIAL (needs the
cluster, the CNI, or another file) or NO (needs a node or the control plane). The last
column is the trap that turns a naive hit into a false positive.

PSS is cumulative and evaluated **per container**: pod-level `securityContext` only sets
defaults, and a container that sets its own value wins.

## PSS Baseline (all must be nil/false/empty)

| Check | Bad value | Static | Freq | Impact | False-positive trap |
|---|---|---|---|---|---|
| Host namespaces | `hostNetwork`, `hostPID`, `hostIPC`, `shareProcessNamespace: true` | YES | med | high | `hostNetwork: true` on a CNI/DNS DaemonSet is sometimes intended — still report, say why it is there |
| Privileged | `securityContext.privileged: true` | YES | med | high | gated by a values flag that renders false; privileged in a rootless Podman dev sandbox is not host root |
| Capabilities added | `capabilities.add` outside `AUDIT_WRITE CHOWN DAC_OVERRIDE FOWNER FSETID KILL MKNOD NET_BIND_SERVICE SETFCAP SETGID SETPCAP SETUID SYS_CHROOT` | YES | med | high | `NET_BIND_SERVICE` is in the allowlist; `SYS_ADMIN`/`NET_ADMIN`/`SYS_PTRACE` are not |
| hostPath volumes | any `volumes[*].hostPath` | YES | high | high | a read-only `/var/log` collector is still hostPath (Baseline forbids it) — report, downgrade by read-only + path |
| hostPort | `ports[*].hostPort` non-zero | YES | med | med | hostPort on a DaemonSet is the deployment model; report as exposure, not escape |
| procMount | `procMount: Unmasked` | YES | low | high | — |
| seccomp | `seccompProfile.type: Unconfined` or the `seccomp.security.alpha.kubernetes.io` annotation | YES | high | high | unset is a Baseline pass but a Restricted fail — score it under Restricted, not twice |
| AppArmor | annotation `container.apparmor.security.beta.kubernetes.io/*=unconfined` | YES | low | med | `RuntimeDefault`/`Localhost` are the good values |
| SELinux | `seLinuxOptions.type` not in `container_t container_init_t container_kvm_t container_engine_t`, or non-empty `user`/`role` | YES | low | med | `level:`/`type:` set by the runtime default is fine |
| sysctls | `securityContext.sysctls` with names outside the namespaced-safe list (`net.ipv4.ip_local_port_range`, `net.ipv4.tcp_syncookies`, `kernel.shm_rmid_forced`, …) | YES | low | med | `net.ipv4.ip_forward` and `kernel.*` are unsafe |
| Windows HostProcess | `windowsOptions.hostProcess: true` | YES | low | high | Windows nodes only; if `spec.os.name: windows` is absent it may be dead config |
| Probes with host | `httpGet.host`/`tcpSocket.host` set (1.34+) | YES | low | med | points at a service name, not the node, in most charts |

## PSS Restricted (Baseline + these)

| Check | Bad value | Static | Freq | Impact | False-positive trap |
|---|---|---|---|---|---|
| Privilege escalation | `allowPrivilegeEscalation` not `false` (Linux) | YES | high | high | `privileged: true` already implies it — one finding, not two |
| Non-root | `runAsNonRoot` not `true`, or `runAsUser: 0` | YES | high | high | pod-level `runAsNonRoot: true` with container `runAsUser: 0` is still root |
| readOnlyRootFilesystem | `readOnlyRootFilesystem` not `true` | YES | high | med | an app writing to `/tmp` needs an `emptyDir` — the missing mount is a separate finding |
| seccomp explicit | `seccompProfile.type` absent (Restricted requires `RuntimeDefault`/`Localhost`) | YES | high | med | a namespace-level default does not exist; only the pod/container field counts |
| Capabilities | `capabilities.drop` missing or not `[ALL]`; `add` beyond `NET_BIND_SERVICE` | YES | high | med | `drop: ["all"]` is the same list (case-insensitive); `drop: ["NET_RAW"]` alone is not |
| Volume types | any volume type outside `configMap csi downwardAPI emptyDir ephemeral persistentVolumeClaim projected secret` | YES | high | med | `hostPath`, `nfs`, `iscsi`, `gitRepo` are the usual offenders |

## Workload rows outside PSS

| Check | Bad value | Static | Freq | Impact | False-positive trap |
|---|---|---|---|---|---|
| SA token automount | `automountServiceAccountToken` unset/`true` on a workload that never calls the API | YES | high | high | a controller that must talk to the API needs it — check for RBAC it uses |
| Default ServiceAccount | pod runs as `default` with a token mounted | YES | high | med | `automountServiceAccountToken: false` at pod level covers it |
| Resource limits | no `resources.limits` (cpu+memory) on any container | YES | high | med | a cluster-wide `LimitRange` may supply it — cluster state, PARTIAL |
| Quota | no `ResourceQuota` in the namespace manifest | PARTIAL | med | med | the namespace may be managed elsewhere; PARTIAL, never a standalone finding |
| Image pinning | `:latest`/mutable tag, no digest | YES | high | low | info note; a finding only with an untrusted registry or no digest admission |
| Image pull policy | `imagePullPolicy: Always` with a mutable tag | YES | med | low | note only |
| `gitRepo` volume | any use | YES | low | high | deprecated volume type with a command-execution CVE (CVE-2024-10220) — report every use |
| `docker.sock` hostPath | `/var/run/docker.sock` or `/run/containerd/containerd.sock` in a volume | YES | med | high | read-only does **not** make the daemon API read-only |

## RBAC

| Check | Bad value | Static | Freq | Impact | False-positive trap |
|---|---|---|---|---|---|
| cluster-admin binding | `RoleBinding`/`ClusterRoleBinding` whose `roleRef.name` is `cluster-admin` | YES | high | high | binding to a group that does not exist is dormant but still reportable |
| Wildcards | `apiGroups: ["*"]`, `resources: ["*"]`, `verbs: ["*"]` | YES | high | high | `resources: ["*"]` under `resourceNames` is narrower — read the whole rule |
| Escalation verbs | `escalate`, `bind`, `impersonate` on roles/clusterroles/users/groups/serviceaccounts | YES | med | high | `bind` limited to one low-privilege role is a real design; report the target role |
| SA token minting | `create` on `serviceaccounts/token` | YES | med | high | TokenRequest from a controller is the intended use — check which SAs it can target |
| Node proxy | `get`/`create` on `nodes/proxy`, `nodes/log`, `nodes/stats` | YES | low | high | metrics agents need `nodes/stats`; `nodes/proxy` bypasses audit and admission |
| Secrets read | `get`/`list`/`watch` on `secrets` (cluster-wide especially) | YES | high | high | `list` and `watch` are as bad as `get` |
| Workload creation | `create`/`patch` on `pods`, `deployments`, `daemonsets`, `jobs`, `cronjobs` | YES | med | high | creating pods inherits any SA and mounts any Secret in that namespace |
| PV creation | `create` on `persistentvolumes` | YES | low | high | a `hostPath` PV is node access |
| Webhook config write | `create`/`patch` on `validatingwebhookconfigurations`/`mutatingwebhookconfigurations` | YES | low | high | reads/mutates everything admitted |
| Namespace patch | `patch`/`update` on `namespaces` | YES | low | high | flips PSA labels and breaks NetworkPolicy isolation |
| CSR approval | `create` CSRs + `update` on `certificatesigningrequests/approval` | YES | low | high | mints arbitrary client certs |
| system:masters | `subjects` with group `system:masters`; `system:unauthenticated`/`system:authenticated` bindings | YES | low | high | `system:authenticated` to a read-only role is the only defensible case |
| Aggregated roles | `aggregationRule` clusterRoles | PARTIAL | low | med | effective verbs depend on labels present in the cluster |

## NetworkPolicy

| Check | Bad value | Static | Freq | Impact | False-positive trap |
|---|---|---|---|---|---|
| Default-deny exists | no `podSelector: {}` policy in the namespace | PARTIAL | high | high | absence in this repo is not absence in the cluster; a CNI without NetworkPolicy support ignores the policy anyway |
| Egress covered | `policyTypes` missing `Egress` | YES | high | high | a namespace where nothing egresses still deserves the deny |
| Ingress covered | `policyTypes` missing `Ingress` | YES | high | med | — |
| Wide-open ports | `ports: [{port: 0, endPort: 65535}]` or no `ports` with an open peer | YES | med | med | no `ports` means all ports, which is what a default-deny allow-list sometimes needs |
| Empty peer | `from: [{}]` / `to: [{}]` or empty `podSelector` | YES | med | high | `podSelector: {}` inside `from` means "all pods in this namespace" — often intended |
| IMDS egress | egress allowed to `169.254.169.254` (metadata) or `0.0.0.0/0` | PARTIAL | med | high | blocked by the CNI/node firewall in some clusters — PARTIAL, not a bare finding |

## Secrets and values

| Check | Bad value | Static | Freq | Impact | False-positive trap |
|---|---|---|---|---|---|
| Plaintext credential in values | `password`/`token`/`apiKey` with a literal value in `values*.yaml` | YES | high | high | `existingSecret`/`secretRef` is the fix; an empty or `changeme` placeholder is a different (lower) issue |
| Credential in `Secret` manifest | `data`/`stringData` with a real value | YES | high | high | base64 in `data` is encoding, not encryption — the value is readable |
| Secret as env var | `env[].valueFrom.secretKeyRef` for credentials | YES | med | med | CIS prefers files; env vars leak into crash dumps and child processes |
| `.env`/kubeconfig committed | credentials or a kubeconfig in the repo | YES | med | high | a kubeconfig with a client cert is cluster access — treat as high |

## Exposure

| Check | Bad value | Static | Freq | Impact | False-positive trap |
|---|---|---|---|---|---|
| Service type | `type: NodePort` / `LoadBalancer` for an internal app | YES | high | med | an ingress controller legitimately uses LoadBalancer |
| Ingress TLS | no `spec.tls`, or `secretName` missing | YES | high | med | TLS terminated at the LB/annotated upstream is documented, not inferred |
| Ingress class annotations | `nginx.ingress.kubernetes.io/*` snippets, `configuration-snippet`, `auth-url`, `mirror-target` | YES | low | high | these fed CVE-2025-1974 (ingress-nginx RCE) — report the annotation, not the CVE |
| Dashboard/API exposed | `kubernetes-dashboard`, `kube-proxy` metrics, `:10250`/`:2379` published | YES | low | high | — |
| `hostNetwork` on an ingress controller | binds node ports | YES | low | high | intended in many installs; report with the port |

## Supply chain

| Check | Bad value | Static | Freq | Impact | False-positive trap |
|---|---|---|---|---|---|
| Registry trust | image from a public registry for a first-party service | PARTIAL | high | med | a mirror/proxy registry is fine if it is the org's |
| Digest pinning | tag only, no `@sha256:` | YES | high | med | `mutateDigest` in Kyverno pins at admission — cluster state, PARTIAL |
| Signature verification | no `verifyImages`/policy-controller policy in the repo | PARTIAL | med | high | the policy may live in the platform repo |

## Not static (record under `coverage.excluded`, never report)

- Control plane: apiserver/etcd/scheduler flags, anonymous auth, audit config, encryption
  at rest, certificate expiry.
- Kubelet: `--anonymous-auth`, read-only port 10255, `--protect-kernel-defaults`.
- Node: file permissions on kubeconfigs, container runtime config, kernel/LSM state.
- Runtime: which pods actually run, Falco events, image CVEs (needs a pulled image),
  CNI policy enforcement, effective RBAC after aggregation.
- CIS Kubernetes section 5 says "Automated" for things it audits with `kubectl` against a
  live cluster. From artifacts the question is "is the field bad in this YAML", not "does
  CIS check 5.2.x pass".
