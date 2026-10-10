# Pwnagotchi

> **This is a modified fork** of [jayofelony/pwnagotchi](https://github.com/jayofelony/pwnagotchi), which is itself based on [evilsocket's pwnagotchi](https://github.com/evilsocket/pwnagotchi). It is not the official project and is not endorsed by its authors.
>
> **What's different here:** the `ai-mode` branch (the default) restores the reinforcement-learning AI that upstream removed, as an **opt-in** feature that is **off by default**. Turn it on in `/etc/pwnagotchi/config.toml`:
>
> ```toml
> [ai]
> enabled = true
> ```
>
> The AI needs extra Python packages (`pip install 'pwnagotchi[ai]'`), is included in images built from this branch, and is **experimental**: upstream removed it because it reportedly destabilised the Wi-Fi firmware, and it has only been tried on one Raspberry Pi 4 so far. Turn it off again if your Wi-Fi chip starts crashing.
>
> 📖 **[Read AI_MODE_HARDWARE_NOTES.md](docs/AI_MODE_HARDWARE_NOTES.md) before you flip this on** — it covers the exact hardware this has been run on (an external USB adapter doing capture instead of the onboard chip, and why that setup may avoid the original Wi-Fi-firmware failure mode), a real SIGILL crash that was found and fixed getting AI mode running on a Pi 4, every patch required with full diffs, and an honest status report including the issues that are *not* fixed yet.
>
> Images built from this branch also boot by partition label rather than PARTUUID, use a CPU-only PyTorch, and **do not auto-update from upstream** (that would replace this fork). The `noai` branch is the AI-free version this was started from.
>
> To build an image yourself, see [Building an image](#building-an-image). This fork is licensed under the same GPLv3 as upstream; see [LICENSE.md](LICENSE.md). All credit for the original work goes to the upstream authors.

This is the main source for all forks:
- RPiZeroW (32bit) older versions work, no more new releases as it now more a legacy device
- RPiZero2W, RPi3, RPi4, RPi5 (64bit)

**For installation docs check out the [wiki](https://github.com/jayofelony/pwnagotchi/wiki)!**

If you want to sponsor this project you can use GH Sponsor or cryptocurrency:

[GH Sponsor](https://github.com/sponsors/jayofelony)

Or send some ethereum: 0x33ceC4Abe80fDE460a924d596d4dE31Bc0767bb6

**Proudly partnering with [PiSugar](https://www.pisugar.com)!!**

---

[Pwnagotchi](https://pwnagotchi.org/) is a Raspberry Pi leveraging [bettercap](https://www.bettercap.org/) that survives from its surrounding Wi-Fi environment to maximize the crackable WPA key material it captures (either passively, or by performing authentication and association attacks). This material is collected as PCAPNG files containing any form of handshake supported by [hashcat](https://hashcat.net/hashcat/), including [PMKIDs](https://www.evilsocket.net/2019/02/13/Pwning-WiFi-networks-with-bettercap-and-the-PMKID-client-less-attack/), 
full and half WPA handshakes.

![ui](https://i.imgur.com/X68GXrn.png)

The "old" Pwnagotchi used to have AI to help it learn from its environment, but since then AI seemed to destabilize the Wi-Fi firmware. So I have chosen to remove the AI completely to give the Pwnagotchi more up-time and longer battery life when taking it on a walk.

Multiple units within close physical proximity can "talk" to each other, advertising their presence to each other by broadcasting custom information elements using a parasite protocol [@evilsocket](https://x.com/evilsocket) built on top of the existing dot11 standard.

## Documentation

https://github.com/jayofelony/pwnagotchi/wiki 
https://pwnagotchi.org

## Links

| &nbsp;    | Official Links                                           |
|-----------|----------------------------------------------------------|
| Website   | [pwnagotchi.org](https://pwnagotchi.org/)                  |
| Chat      | [discord](https://discord.gg/PGgnzFbz4M) |
| Subreddit | [r/pwnagotchi](https://www.reddit.com/r/pwnagotchi/)     |

## Building an image

Images are built with [pi-gen](https://github.com/RPi-Distro/pi-gen) on **Linux** (Ubuntu/Debian, or Ubuntu under WSL2 on Windows). Work inside the Linux filesystem (`~`), not `/mnt/c`. Plan for about 20 GB of free disk and a few hours.

```bash
sudo apt-get update && sudo apt-get install -y make git quilt qemu-user-static debootstrap zerofree libarchive-tools curl pigz arch-test qemu-utils qemu-system-arm qemu-user gcc-aarch64-linux-gnu debhelper dh-sequence-dkms dpkg-dev parted zip dosfstools
```

Check that ARM emulation is registered (this should print `qemu-aarch64`):

```bash
ls /proc/sys/fs/binfmt_misc/ | grep -i aarch64
```

Get this branch, its submodules, and put pi-gen on the branch the Makefile expects:

```bash
git clone -b ai-mode https://github.com/tedead/pwnagotchi-64.git && cd pwnagotchi-64 && make submodules
cd pi-gen-64bit && git checkout arm64 && git pull && cd ..
```

Build the 64-bit image (Raspberry Pi 3/4/5 and Zero 2 W):

```bash
make 64bit 2>&1 | tee ~/build.log
```

The finished `.img.xz` is written to `~/images`. Flash it with Raspberry Pi Imager ("Use custom") or balenaEtcher.

Notes:
- The image build clones **this** repo (`ai-mode`) from GitHub, so push your changes before building. Override with `PWN_REPO` / `PWN_BRANCH` to build another fork or branch.
- The submodules (pi-gen, bettercap, pwngrid, nexmon) still come from the upstream author's repositories; they are build tooling and the network/Wi-Fi components, not the pwnagotchi code.
- AI mode is **off by default** in the built image. See the top of this README to enable it.

## License

`pwnagotchi` created by [@evilsocket](https://x.com/evilsocket) and updated by [us](https://github.com/jayofelony/pwnagotchi/graphs/contributors). It is released under the GPL3 license.
