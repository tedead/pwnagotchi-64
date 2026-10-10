# AI mode on real hardware: setup, patches, and why this rig doesn't see the original crash

This documents a working `[ai] enabled = true` setup on a Raspberry Pi 4, running
[tedead/pwnagotchi-64](https://github.com/tedead/pwnagotchi-64) (`ai-mode` branch — AI
restored from the deep-RL code removed from `jayofelony/pwnagotchi-torch` in commit
`af632abc`). It covers the hardware, the patches required to make AI mode boot without
crashing, and a hypothesis — clearly marked as a hypothesis, not a proven fact — for why
this particular hardware combination hasn't reproduced the instability that reportedly
motivated removing AI mode in the first place.

## Hardware

| Interface | Chip | Driver | Firmware | Role |
|---|---|---|---|---|
| `wlan0` | Broadcom BCM4345/6 (onboard, SDIO) | `brcmfmac` | `brcmfmac43455-sdio`, v7.45.265, **nexmon-patched** (`28bca26 CY nexmon.org: 1654e-1`) | Unused — left up but never does capture |
| `wlan1` | MediaTek MT7612U (ALFA AWUS036ACM, USB) | `mt76x2u` | ASIC rev `76120044`, fw `0.0.00` build `1` (2015-07-31), **stock vendor firmware** | Actual capture/injection radio |
| `eth0` | Broadcom GENET (onboard) | `bcmgenet` | — | Primary wired uplink |

Kernel: `6.18.50+rpt-rpi-v8`.

**The key hardware fact this whole write-up hinges on:** the onboard Broadcom chip
can only do monitor mode and frame injection because its firmware has been patched by
[nexmon](https://github.com/seemoo-lab/nexmon) — those capabilities aren't native to the
chip. It also sits on SDIO, a bus with a known history of backplane wedges under this kind
of load (see the `reload_brcm()` / SDIO-wedge-reboot logic already in `pwnlib`, written
specifically to work around this). The MT7612U, by contrast, supports monitor mode and
injection **natively**, runs **unmodified vendor firmware**, and talks to the Pi over USB
instead of SDIO. It is not the same class of component.

## Network architecture

- `wlan1` (ALFA, MT7612U) is the only interface bettercap ever puts into monitor mode.
  It's intentionally the fixed, permanent capture radio.
- `wlan0` (onboard) is left up but is never used for capture. Both `wlan0` and `wlan1` are
  marked permanently unmanaged in NetworkManager (`/etc/NetworkManager/conf.d/`) so a
  radio-stack hiccup can't let NetworkManager grab either one and eat the routing table.
- `eth0` is the primary uplink (lowest route metric); a secondary USB Wi-Fi dongle exists
  as a backup uplink path but isn't part of the capture/AI story.

## Patches required to run AI mode without crashing

None of these are upstream — they're specific to this fork's wlan1-based hardware setup
and to a real crash found while bringing AI mode up on this Pi 4. All are small, targeted
diffs, not rewrites.

### 1. Point capture at `wlan1` instead of `wlan0` (`/usr/bin/pwnlib`)

Stock `start_monitor_interface`/`stop_monitor_interface` hard-code `wlan0`/`wlan0mon`.
Patched to use `wlan1`/`wlan1mon` for everything except the onboard-chip-specific
`reload_brcm()` recovery path, which is left untouched since it's brcmfmac/SDIO-wedge
recovery and has nothing to do with which radio does capture:

```diff
-  if ! ifconfig wlan0 up; then
-    echo "start_monitor_interface: failed to bring up wlan0" >&2
+  if ! ifconfig wlan1 up; then
+    echo "start_monitor_interface: failed to bring up wlan1" >&2
     return 1
   fi

-  if ! wait_for_interface wlan0 10; then
-    echo "start_monitor_interface: wlan0 not ready" >&2
+  if ! wait_for_interface wlan1 10; then
+    echo "start_monitor_interface: wlan1 not ready" >&2
     return 1
   fi

   local phy
-  phy="$(phy_for_interface wlan0)"
+  phy="$(phy_for_interface wlan1)"
   ...
-  if ! iw phy "$phy" interface add wlan0mon type monitor; then
+  if ! iw phy "$phy" interface add wlan1mon type monitor; then
   ...
-ifconfig wlan0 down
-ifconfig wlan0mon up
+ifconfig wlan1 down
+ifconfig wlan1mon up
   ...
 stop_monitor_interface() {
-  if [ -e /sys/class/net/wlan0mon ]; then
-    ifconfig wlan0mon down
-    iw dev wlan0mon del
+  if [ -e /sys/class/net/wlan1mon ]; then
+    ifconfig wlan1mon down
+    iw dev wlan1mon del
   fi
   reload_brcm
-  ifconfig wlan0 up
+  ifconfig wlan1 up
 }
```

### 2. Launch bettercap on `wlan1mon` (`/usr/bin/bettercap-launcher`)

```diff
 if is_auto_mode_no_delete; then
-  /usr/local/bin/bettercap -no-colors -caplet pwnagotchi-auto -iface wlan0mon
+  /usr/local/bin/bettercap -no-colors -caplet pwnagotchi-auto -iface wlan1mon
 else
-  /usr/local/bin/bettercap -no-colors -caplet pwnagotchi-manual -iface wlan0mon
+  /usr/local/bin/bettercap -no-colors -caplet pwnagotchi-manual -iface wlan1mon
 fi
```

### 3. Point pwngrid at `wlan1mon` (`/etc/systemd/system/pwngrid-peer.service`)

```diff
-After=bettercap.service sys-subsystem-net-devices-wlan0mon.device
+After=bettercap.service sys-subsystem-net-devices-wlan1mon.device
 ...
-ExecStartPre=/bin/sh -c 'for i in $(seq 1 60); do [ -e /sys/class/net/wlan0mon ] && exit 0; sleep 1; done; exit 0'
-ExecStart=... -iface wlan0mon
+ExecStartPre=/bin/sh -c 'for i in $(seq 1 60); do [ -e /sys/class/net/wlan1mon ] && exit 0; sleep 1; done; exit 0'
+ExecStart=... -iface wlan1mon
```

### 4. Teach `fix_services.py` about the external adapter

The stock `Fix_Services` plugin auto-disables itself when it detects a non-`brcmfmac`
driver — but it only ever checked `wlan0`'s driver, never `wlan1`'s. On this hardware
`wlan0` *is* brcmfmac (just unused), so the plugin wrongly concluded "onboard chip
present, stay active" and then endlessly chased a `wlan0mon` interface that is never
created, spamming `CalledProcessError` every epoch. Fix: check `wlan1` first.

```diff
             interfaces = os.listdir("/sys/class/net/")

+            # This fork's capture radio is wlan1 (external USB adapter);
+            # wlan0 (onboard brcmfmac) is intentionally left unmanaged and
+            # unused. Check wlan1 first so the plugin correctly disables
+            # itself here instead of endlessly chasing wlan0mon, which is
+            # never created on this hardware setup.
+            if 'wlan1' in interfaces:
+                try:
+                    driver_path = "/sys/class/net/wlan1/device/driver"
+                    if os.path.exists(driver_path):
+                        driver_link = os.readlink(driver_path)
+                        driver_name = os.path.basename(driver_link)
+                        logging.info(f"[Fix_Services] Detected wlan1 driver: {driver_name}")
+                        if driver_name != "brcmfmac":
+                            logging.info(f"[Fix_Services] External WiFi adapter detected on wlan1 ({driver_name}). Plugin will be disabled.")
+                            return True
+                except Exception as e:
+                    logging.warning(f"[Fix_Services] Error checking wlan1 driver: {e}.")
+
             # Look for wlan0 interface
             if 'wlan0' in interfaces:
```

Confirmed result after this patch: `[Fix_Services] Detected wlan1 driver: mt76x2u` →
`External WiFi adapter detected on wlan1 (mt76x2u). Plugin will be disabled.` — no more
spurious errors.

### 5. A real crash in AI mode itself: SIGILL in torch, not a Wi-Fi problem

With 1–4 in place, enabling `[ai] enabled = true` crashed `pwnagotchi.service` in a tight
restart loop. `systemctl` showed `status=132/n/a` — **exit code 132 = killed by SIGILL
(illegal instruction)**, not a Python exception (SIGILL bypasses `try`/`except`
entirely, which is why nothing useful showed up in the debug log).

Reproduced standalone, outside the full pwnagotchi process, by constructing the same
`pwnagotchi.ai.gym.Environment` + `A2C(MlpPolicy, env, **config['ai']['params'])` that
`pwnagotchi/ai/__init__.py` builds on startup. Crashed reliably. A plain CartPole env with
a small `Discrete(2)`/`Box(4,)` space did **not** crash — this env's much larger
`MultiDiscrete` action space (52 dimensions, up to 571 each) and `(1, 707)` observation
space does.

Root cause: on this Pi 4 (aarch64), torch's vectorized CPU kernels hit a race between
multiple native thread pools (torch's own + OpenBLAS/MKL) when building the policy
network for this size of action space. Forcing single-threaded execution
(`OMP_NUM_THREADS=1` + `torch.set_num_threads(1)`) made the exact same reproduction
succeed reliably across repeated runs.

Fix, in two places (belt and suspenders — the env vars guarantee it's set before any
native lib initializes its thread pool, regardless of how the process is launched; the
in-code call is defense in depth):

`/etc/systemd/system/pwnagotchi.service`:
```diff
 [Service]
 Type=simple
+Environment=OMP_NUM_THREADS=1
+Environment=OPENBLAS_NUM_THREADS=1
+Environment=MKL_NUM_THREADS=1
 WorkingDirectory=~
```

`pwnagotchi/ai/__init__.py`:
```diff
         logging.info("[AI] bootstrapping dependencies ...")

+        # on the Pi 4 (aarch64), torch's vectorized CPU kernels can hit a
+        # SIGILL (illegal instruction, exit 132) when multiple native thread
+        # pools (torch's own + OpenBLAS/MKL) race during model construction
+        # for a large MultiDiscrete action space - this crashes the whole
+        # process with no Python traceback since SIGILL bypasses try/except.
+        # Forcing single-threaded torch avoids the race. Must happen before
+        # torch itself is imported/initializes its thread pool.
+        start = time.time()
+        import torch
+        torch.set_num_threads(1)
+        logging.debug("[AI] torch imported and pinned to 1 thread in %.2fs" % (time.time() - start))
+
         start = time.time()
         from stable_baselines3 import A2C
```

After this, AI mode boots clean every time (`NRestarts=0`), trains, re-tunes
`[personality]` parameters every episode, and checkpoints `/root/brain.nn` /
`/root/brain.json` periodically.

### 6. Image size / correctness: CPU-only torch wheel

Not a crash fix, but worth stating plainly: `pip3 install '.[ai]'` alone resolves the
default PyPI `torch`, which is a **CUDA build** — nonsensical on a Pi with no NVIDIA GPU,
and it drags in ~3.3GB of unused `nvidia-*` wheels. The repo's build script now installs
the CPU-only wheel first so pip sees `torch` as already satisfied:

```bash
# A Pi has no NVIDIA GPU. The default PyPI torch is a CUDA build that drags in ~3.3GB of
# nvidia-* wheels, so install the CPU-only wheel first; pip then sees torch as satisfied.
pip3 install torch --index-url https://download.pytorch.org/whl/cpu --no-cache-dir
pip3 install '.[ai]' --no-cache-dir
```

(`stage3/04-install-pwnagotchi/01-run-chroot.sh`)

## Why this setup likely doesn't see the original instability — a hypothesis, not a proven fact

The commit that removed AI mode (`af632abc`, upstream `jayofelony/pwnagotchi-torch`) has
no rationale in its message or diff — it's just `"Update build"` with the AI code deleted
outright. So the specific claim "AI mode made the Wi-Fi firmware unstable" can't be
verified from git history directly; it's circulated community knowledge, not something in
the commit itself. One thing the old deleted code *does* independently confirm: on any
startup exception it ran `rm /root/brain.nn && service pwnagotchi restart` — a real,
separate bug (self-inflicted restart-loop with brain deletion on any error, not
specifically a Wi-Fi one) that's gone in the restored code's error handling.

That said, if the instability was real, the mechanism is plausible: AI mode drives much
more varied, less hand-tuned channel-hop timing and parameter changes than the heuristic
strategy, as it explores during training. On stock hardware that aggressiveness lands on
`wlan0` — a chip running **hacked firmware** to do something (monitor mode + injection)
it wasn't designed for, over SDIO, a bus with a known wedge history on this chip. On this
rig, none of that AI-driven exploration ever touches `wlan0` at all — capture runs
exclusively on `wlan1`, a chip that does monitor mode and injection **natively**, with
**stock firmware**, over USB.

So: a structural reason to expect this setup to be meaningfully less prone to the original
failure mode, not just "hasn't happened yet." But it genuinely hasn't been proven —
only watched for a few hours of real training so far, not exhaustively. Treat it as a
reasonable, falsifiable hypothesis, and report back if anything changes.

## Current verification status (as of this writing)

- AI mode enabled, training, actively re-tuning `[personality]` params every episode,
  reward trending upward across epochs, `brain.nn`/`brain.json` checkpointing normally.
- Survived a clean reboot and several hours of live AI training with no recurrence of
  the SIGILL described above, and no `brcmfmac`/`mt76`/illegal-instruction/segfault/panic
  entries in `dmesg` beyond normal monitor-mode enter/leave logging.

**Being honest about what else turned up during extended monitoring, so this isn't
overstated as "zero issues":**

- **A separate, pre-existing, self-healing `bettercap` crash** (`status=2/INVALIDARGUMENT`,
  `command failed: Operation not supported (-95)` in bettercap's own log) recurs roughly
  every 1–1.5 hours. `systemd`'s `Restart=always` brings it back within ~30 seconds each
  time. **This is not caused by AI mode** — the same crash was observed at 17:37:46,
  *before* `[ai] enabled` was even flipped to `true` (that happened at 17:46). Root cause
  not yet pinned down; the channel active at each occurrence hasn't lined up cleanly with
  a single obvious trigger (e.g. DFS channels), so take the errno (`ENOTSUP`) as a hint
  about the `mt76x2u` driver rejecting some operation bettercap asks for, not a confirmed
  diagnosis. Self-heals, but is a real, recurring hiccup worth knowing about if you're
  running this setup.
- **An unrelated bug in the `ohcapi.py` plugin** (the OnlineHashCrack submission pipeline):
  `_run_tasks()` migrates its `reported` handshake-tracking field from a dict (`{path:
  size}`) to a plain list, but a later line (`elif current_size > reported[p]`) still
  indexes it like a dict, throwing `TypeError: list indices must be integers or slices,
  not String` on every UI update. Caught and logged, not fatal, but it means the "re-
  upload a `.pcapng` that grew after it was first reported" feature is currently broken.
  Also unrelated to AI mode or Wi-Fi hardware — a plain logic bug.

Neither of these is the SIGILL/torch issue this document is mainly about, and neither has
caused a sustained crash loop or made the device unreachable. They're noted here so this
write-up doesn't read as "everything is perfect" when the fuller multi-hour picture is
"the specific AI-mode-breaking bug is fixed; a couple of smaller, pre-existing, non-fatal
issues are still open."
