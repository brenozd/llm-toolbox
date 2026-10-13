---
name: distrobox
description: "Persistent per-project distrobox container (Ubuntu 24.04, systemd) to build and test code isolated from the host. Use for: \"run this in a sandbox\", \"test in a container\", \"I need systemd to test this\", /distrobox."
allowed-tools:
  - Bash
  - Read
  - AskUserQuestion
---

# distrobox

Persistent per-project distrobox for building/testing system-level or
host-risky code. Own HOME, systemd, host dep caches mounted so it stays fast.
Kept between runs; destroyed on request.

## Trigger

User says: "run/test this in a sandbox", "isolated environment", "distrobox",
"I need systemd", "don't run that on my host", or `/distrobox`.
`/distrobox clean` → skip to step 6 (destroy).

## Workflow

1. **Derive names** from the project cwd:

   ```bash
   PROJ_DIR="$PWD"
   NAME="sbx-$(basename "$PROJ_DIR")-$(printf %s "$PROJ_DIR" | sha1sum | cut -c1-6)"
   HOME_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/sandbox-homes/$NAME"
   IMAGE="quay.io/toolbx/ubuntu-toolbox:24.04"
   ```

   The name is stable per project dir, so re-runs reuse the same container.

2. **Ask about extra volumes.** Use `AskUserQuestion` (or a plain question) —
   "Mount anything besides the project and the standard dep caches?".
   Collect zero or more `host:container` pairs. Default: none.

3. **Create** (skip entirely if `distrobox list` already shows `$NAME` — just
   `enter` it). Dep caches are mounted from the host so the container shares
   downloads with normal host builds; only create the dirs that make sense for
   the project's stack:

   ```bash
   mkdir -p "$HOME_DIR" \
     "$HOME/.cache/pip" "$HOME/.npm" "$HOME/.cargo/registry" \
     "$HOME/.cache/go-build" "$HOME/.cache/sandbox-apt"

   distrobox create \
     --name "$NAME" \
     --image "$IMAGE" \
     --home "$HOME_DIR" \
     --init \
     --yes \
     --volume "$PROJ_DIR:/opt/$(basename "$PROJ_DIR"):rw" \
     --volume "$HOME/.cache/pip:$HOME_DIR/.cache/pip:rw" \
     --volume "$HOME/.npm:$HOME_DIR/.npm:rw" \
     --volume "$HOME/.cargo/registry:$HOME_DIR/.cargo/registry:rw" \
     --volume "$HOME/.cache/go-build:$HOME_DIR/.cache/go-build:rw" \
     --volume "$HOME/.cache/sandbox-apt:/var/cache/apt/archives:rw" \
     --additional-packages "systemd libpam-systemd" \
     --absolutely-disable-root-password-i-am-really-positively-sure
   # add one --volume per extra pair from step 2
   ```

4. **Run** the user's commands inside, working dir set to the mounted project:

   ```bash
   distrobox enter "$NAME" -- bash -lc 'cd /opt/<basename> && <commands>'
   ```

   For systemd-dependent tests, `--init` gives a real PID 1; `systemctl` works.

5. **Report** stdout/exit codes back to the user.

6. **Clean up** — only when the user asks (`/distrobox clean`, "destroy it", "I'm
   done"). Persistent by default.

   ```bash
   distrobox rm -f "$NAME"
   rm -rf "$HOME_DIR"          # keeps the shared host dep caches
   ```

## Notes

- First `create` with a fresh image pulls ~500MB — warn the user it may take a minute.
- The project is mounted, not copied: writes inside the container hit real files.
  If the commands are destructive, mount `:ro` or `git stash` first.
- `--init` needs `podman` ≥ 4.x on the host (Fedora default is fine).
- Dep caches are *shared with the host*, not just persisted — a `pip install` in
  the sandbox warms the cache for host builds too. Isolation is process/FS/init,
  not download history. If the user wants caches isolated as well, point the
  `--volume` sources at dirs under `$HOME_DIR` instead.
- Container HOME (`$HOME_DIR`) survives between runs but is wiped on cleanup;
  anything worth keeping goes in the mounted project or an explicit extra volume.
- Path inside the container is `/opt/<basename>`, not the host path — build configs
  with absolute host paths baked in will break.
