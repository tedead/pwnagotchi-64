# Pwnagotchi AI-mode on a Raspberry Pi 4 with an external ALFA adapter

A step-by-step guide to replicating this build: **AI (reinforcement-learning) mode
re-enabled**, with an **external ALFA Wi‑Fi adapter doing all the capturing** instead of
the Pi's onboard radio. Optional e‑paper display and a ramping fan HAT are covered too.

> [!WARNING]
> **Only use this against networks you own or have explicit written permission to test.**
> Capturing handshakes from, or deauthing, networks you don't control is illegal in most
> jurisdictions. This guide assumes a lab/own-network setup and uses a **passive**
> posture (`deauth = false`) by default. You are responsible for how you use it.

---

## 1. What you'll end up with

| Interface | Role |
|---|---|
| `eth0` (or a second USB Wi‑Fi dongle) | internet / SSH uplink |
| `wlan0` (onboard Broadcom) | **unused** — left idle, kept away from NetworkManager |
| `wlan1` (external ALFA, MT7612U) | **capture** → `wlan1mon` monitor interface |

Plus: AI mode training/running without the Pi‑4 `torch` crash, an e‑paper status
display, and a temperature-ramped fan.

### Why an external adapter?
The onboard Broadcom chip works via nexmon but is 2.4 GHz‑only in monitor mode and is
the same radio the OS wants for other things. An ALFA **AWUS036ACM (MediaTek MT7612U)**
does dual‑band monitor + injection on a mainline driver (`mt76x2u`), so capture is more
reliable and covers 5 GHz. **The catch: the stock image hard-codes the onboard radio for
capture, so you have to repoint it — that's section 6, the core of this guide.**

---

## 2. Hardware

| Item | Notes |
|---|---|
| Raspberry Pi 4 (2 GB+; 4 GB recommended) | AI mode + torch wants the RAM headroom |
| USB boot drive or good SD card | the image is large with the AI extra |
| **ALFA AWUS036ACM** (MT7612U) | the capture adapter; any solid MT7612U works |
| Ethernet, **or** a second USB Wi‑Fi dongle | for internet/SSH while `wlan1` captures |
| *(optional)* Waveshare 2.7" e‑Paper HAT **Rev 2.2** | driver string `waveshare2in7_v2` |
| *(optional)* fan HAT on GPIO14 | e.g. 52Pi EP‑0152 |

---

## 3. Flash the image

This build uses the AI‑mode fork (upstream removed the RL AI; this restores it) and
includes the Pi‑4 `torch` fix (see §7).

1. Build or download the fork's 64‑bit image.
2. Flash it to your USB drive / SD card (Raspberry Pi Imager, Balena Etcher, etc.).
3. Before first boot, you can drop a `config.toml` on the **boot partition** to
   pre-seed pwnagotchi settings (not Wi‑Fi). Or configure everything after boot — this
   guide does it after boot.

---

## 4. First boot & connect

1. Plug in **ethernet** (simplest) and power on. Give it a few minutes on first boot.
2. Find its IP from your router and SSH in (default user `pi`):
   ```bash
   ssh pi@<pi-ip>
   ```
3. Confirm your adapters are present and note their MAC addresses:
   ```bash
   for i in /sys/class/net/wlan*; do echo "$(basename $i): $(cat $i/address)"; done
   ```
   You should see the onboard radio and the ALFA. Identify which is the ALFA by its MAC
   (ALFA/MediaTek OUIs commonly start `00:c0:ca`).

> [!TIP]
> Do the interface work below **over ethernet** so a Wi‑Fi mistake can't lock you out.

---

## 5. Pin the adapter name (optional but recommended)

If you have more than one USB Wi‑Fi adapter, USB enumeration order can swap `wlan1`/`wlan2`
between reboots. Pin names by MAC so `wlan1` is always the ALFA:

```bash
sudo tee /etc/systemd/network/10-wlan1.link >/dev/null <<'EOF'
[Match]
MACAddress=aa:bb:cc:dd:ee:ff      # <-- your ALFA's MAC
[Link]
Name=wlan1
EOF
sudo reboot
```
After reboot, re-check the name/MAC mapping. (The onboard radio is always `wlan0`.)

---

## 6. ⭐ Repoint capture to the external adapter (the key step)

The image creates and uses **`wlan0mon`** (onboard). Setting `main.iface = "wlan1mon"` in
`config.toml` is **not enough** — the shell/service layer ignores it. You must patch three
shipped files. Back each up first.

> [!IMPORTANT]
> Also **disable auto-update** (see §8) or it can revert these core-file patches.

### 6a. `/usr/bin/pwnlib`
This builds the monitor interface. In **`start_monitor_interface()`** and
**`stop_monitor_interface()`** only, change every `wlan0` → `wlan1` and
`wlan0mon` → `wlan1mon`.

```bash
sudo cp /usr/bin/pwnlib /usr/bin/pwnlib.bak
# wlan0mon appears only inside the monitor functions, so this is safe:
sudo sed -i 's/wlan0mon/wlan1mon/g' /usr/bin/pwnlib
```
Then open the file and, **inside those two functions only**, change the remaining base
`wlan0` references to `wlan1` (the `ifconfig wlan0 up/down`, the `phy_for_interface wlan0`,
the readiness checks):
```bash
sudo nano /usr/bin/pwnlib   # edit within start_/stop_monitor_interface only
```
> [!CAUTION]
> Do **not** blanket replace `wlan0` across the whole file. `reload_brcm()` and the
> manual-mode fallback access point legitimately use the onboard `wlan0`; changing those
> will break them.

### 6b. `/usr/bin/bettercap-launcher`
Point bettercap at `wlan1mon`, and drop the onboard-only driver reload:
```bash
sudo cp /usr/bin/bettercap-launcher /usr/bin/bettercap-launcher.bak
sudo sed -i 's/-iface wlan0mon/-iface wlan1mon/g' /usr/bin/bettercap-launcher
# remove (or comment) the reload_brcm line — it reloads the onboard brcmfmac driver,
# which doesn't apply to an external adapter:
sudo sed -i 's/^reload_brcm$/# reload_brcm (onboard-only; not used with external adapter)/' /usr/bin/bettercap-launcher
```

### 6c. `/etc/systemd/system/pwngrid-peer.service`
```bash
sudo cp /etc/systemd/system/pwngrid-peer.service /etc/systemd/system/pwngrid-peer.service.bak
sudo sed -i 's/wlan0mon/wlan1mon/g' /etc/systemd/system/pwngrid-peer.service
sudo systemctl daemon-reload
```

### 6d. Keep NetworkManager off the capture radios
So NM doesn't grab `wlan1` (or let the idle `wlan0` wander onto a network):
```bash
sudo tee /etc/NetworkManager/conf.d/unmanage-capture.conf >/dev/null <<'EOF'
[keyfile]
unmanaged-devices=mac:aa:bb:cc:dd:ee:ff;mac:11:22:33:44:55:66
EOF
# aa:bb... = ALFA (wlan1), 11:22... = onboard (wlan0)
sudo systemctl reload NetworkManager
nmcli device status      # wlan0 + wlan1 = unmanaged; eth0 (or your dongle) = connected
```

> [!IMPORTANT]
> `bettercap` and `pwngrid` are **independent systemd services**. `systemctl restart
> pwnagotchi` does **not** restart them. Always restart all three together:
> ```bash
> sudo systemctl restart bettercap pwngrid-peer pwnagotchi
> ```
> Verify both landed on the right interface:
> ```bash
> ps aux | grep -E 'bettercap|pwngrid' | grep -v grep   # both must show -iface wlan1mon
> ```

---

## 7. AI mode & the Pi‑4 torch fix

AI mode needs PyTorch, which **SIGILLs (exit 132) on the Pi 4** under its default
multithreading. This fork pins torch to a single thread; make sure your image/service has:

- In `pwnagotchi.service`:
  ```
  Environment=OMP_NUM_THREADS=1
  Environment=OPENBLAS_NUM_THREADS=1
  Environment=MKL_NUM_THREADS=1
  ```
  (These must be in the service `Environment=` — the libraries read them at load time.)
- In `pwnagotchi/ai/__init__.py`: `torch.set_num_threads(1)` early, before any torch work.

If you built from this fork, these are already included. Enable AI in `config.toml`:
```toml
[ai]
enabled = true
```
AI stats (epochs lived/trained) accrue in `/root/brain.json` as it trains.

---

## 8. config.toml (scrubbed template)

Overrides only — defaults live in `/etc/pwnagotchi/default.toml`. **Replace every
placeholder with your own values. Never commit real API keys or your Wi‑Fi details.**

```toml
[main]
name = "mypwny"                       # your unit name
iface = "wlan1mon"                    # documentary; the §6 patches are what actually route capture
# Whitelist = never attack/upload these. Put YOUR OWN networks/BSSIDs here:
whitelist = ["YOUR_SSID", "AA:BB:CC:DD:EE:FF"]
extra_channels = 0                    # 0 = don't auto-discover+persist channels (stops list "ballooning")

[main.plugins.auto-update]
enabled = false                       # keep OFF — it can revert the §6 patches

[ai]
enabled = true

[personality]
deauth = false                        # passive / own-network posture
associate = true                      # set false for fully passive (PMKID/EAPOL from natural reconnects)
channels = [1, 6, 11, 36, 40, 44, 48, 149, 153, 157, 161]   # 2.4 non-overlap + non-DFS 5 GHz
min_rssi = -200

[ui.display]
enabled = true
type = "waveshare2in7_v2"             # Waveshare 2.7" Rev 2.2

[ui.web]
username = "admin"
password = "CHANGE_ME"

[bettercap]
handshakes = "/home/pi/handshakes"

# --- optional cloud cracking: use YOUR OWN keys, keep them out of git ---
[main.plugins.ohcapi]
enabled = false
api_key = "<your-onlinehashcrack-api-key>"
```

Validate before every restart to avoid a crash loop:
```bash
sudo /opt/.pwn/bin/python3 -c "import tomllib; tomllib.load(open('/etc/pwnagotchi/config.toml','rb'))" && echo OK
```

---

## 9. Internet uplink options

- **Ethernet** — nothing to do; `eth0` is managed by default.
- **Second USB Wi‑Fi dongle (`wlan2`)** — let NetworkManager own it:
  ```bash
  sudo nmcli connection add type wifi ifname wlan2 con-name home ssid "YOUR_SSID"
  sudo nmcli connection modify home wifi-sec.key-mgmt wpa-psk wifi-sec.psk 'YOUR_WIFI_PASSWORD'
  sudo nmcli connection modify home connection.autoconnect yes
  sudo nmcli connection up home
  ```
  (Make sure this dongle's MAC is **not** in the unmanaged list from §6d.)

---

## 10. (Optional) Display & fan

**Display:** set `ui.display.type = "waveshare2in7_v2"`. On the 2.7" Rev 2.2, only **KEY3
(GPIO6)** and **KEY4 (GPIO5)** are usable — KEY1/KEY2 sit on SPI chip-select pins the panel
needs. The stock button plugin collides with the e‑paper's RST pin (GPIO17), so leave it
disabled.

**Fan (ramping PWM on GPIO14):** remove any kernel `gpio-fan` overlay from
`/boot/firmware/config.txt` (one owner of GPIO14 only), then:
```bash
sudo tee /usr/local/bin/autofan.py >/dev/null <<'EOF'
#!/usr/bin/env python3
from gpiozero import PWMLED
from time import sleep
fan = PWMLED(14)
OFF, LOW, HIGH = 40.0, 40.0, 65.0
def temp():
    with open("/sys/class/thermal/thermal_zone0/temp") as f:
        return int(f.read()) / 1000.0
while True:
    t = temp()
    fan.value = 0 if t < OFF else max(0.30, min(1.0, 0.30 + (min(t, HIGH) - LOW) / (HIGH - LOW) * 0.70))
    sleep(5)
EOF
sudo tee /etc/systemd/system/autofan.service >/dev/null <<'EOF'
[Unit]
Description=Ramping PWM fan on GPIO14
After=multi-user.target
[Service]
ExecStart=/usr/bin/python3 /usr/local/bin/autofan.py
Restart=always
[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload && sudo systemctl enable --now autofan
```

---

## 11. Verify

```bash
sudo systemctl is-active pwnagotchi bettercap pwngrid-peer autofan
ps aux | grep -E 'bettercap|pwngrid' | grep -v grep     # both on -iface wlan1mon
iw dev | grep -iE 'Interface|type'                       # wlan1mon = monitor
nmcli device status                                      # wlan0/wlan1 unmanaged
vcgencmd get_throttled                                   # 0x0 = power OK
cat /root/brain.json                                     # AI epochs climbing (once training)
ls -l /home/pi/handshakes/                               # .pcapng / .hc22000 appearing
```

Reboot once and re-run the above to confirm everything survives a cold boot.

---

## 12. Cracking captured handshakes (your own networks)

Captures land in `/home/pi/handshakes/` as `.pcapng` (raw) and `.hc22000` (hashcat 22000).
Only **complete** captures (PMKID or full EAPOL) convert to a crackable hash. Pull them off
with `scp` and crack locally:
```bash
hashcat -m 22000 capture.hc22000 wordlist.txt
```
Convert manually if needed: `hcxpcapngtool -o out.hc22000 *.pcapng`.

---

## 13. Troubleshooting / gotchas

- **`wlan1mon ... Device or resource busy`** → NetworkManager is still managing `wlan1`.
  Confirm the unmanaged rule (§6d) applied: `nmcli device status`.
- **Capture still on `wlan0mon` after patching** → you only restarted `pwnagotchi`.
  Restart `bettercap` and `pwngrid-peer` too (they're independent services).
- **Channel list keeps growing on its own** → set `extra_channels = 0`.
- **Config/patches silently revert** → `auto-update` is on; disable it (§8).
- **`torch` service crash-loops (exit 132 / SIGILL)** → the §7 thread pins are missing.
- **AI epochs show "Not available" on opwngrid** → needs the grid plugin enabled + internet;
  and epochs only appear once the AI has actually trained.
- **Remote box, no console** → a Wi‑Fi/NM mistake means a physical trip. Do interface
  changes over ethernet, and consider a connectivity watchdog.

---

*This is a modified fork of pwnagotchi (RL AI mode restored). Credit to the upstream
Pwnagotchi project and the jayofelony image this is based on.*
