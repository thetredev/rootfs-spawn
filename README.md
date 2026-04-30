# rootfs-spawn

## Requirements for populating rootfs directories

Depending on the distro you want to spawn, you need the respective tool:
- Debian/Ubuntu: `debootstrap` or `multistrap` (https://wiki.debian.org/EmDebian/CrossDebootstrap)
- Arch Linux: `pacstrap` (https://wiki.archlinux.org/title/Pacstrap)
- YUM/DNF based (Fedora, RHEL, CentOS Alma Linux, Rocky Linux, ...): `yum` + `dnf` and the respective YUM repo setup (see https://quantum5.ca/2025/03/22/whirlwind-tour-of-systemd-nspawn-containers/#installing-rhel-derivatives-with-dnf for an example)


## Build and run it!

**Prerequisites**:
- [uv](https://docs.astral.sh/uv)

Once the prerequisites are installed on your system, run the following commands to clone the project:
```
git clone https://github.com/thetredev/rootfs-spawn.git
cd rootfs-spawn
```

Then sync the project via `uv`:
```
uv sync
```

Syncing includes installing. If you for any reason need to install it locally `pip`-style, you can run
```
uv pip install .
```
or
```
uv pip install -e .
```

## TODO make this content rich and pretty
