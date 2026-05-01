# rootfs-spawn

## The Vision

Check out the [configs](configs) directory to get an overview of what this project is trying to achieve.

[configs/defaults](configs/defaults) provides default/preset mechanisms for rootfs creation. Currently only Debian 13 is implemented.

[configs/tests](configs/tests) provides config files which users will write to configure their rootfs creation process.

For example:
```
sudo rootfs-spawn create configs/tests/debian.rootfs my-rootfs-output-dir
```

This will kick off the parsing stage:
1. Read and parse the provided config file `configs/tests/debian.rootfs`
2. Process all statements into a list of statements ordered by their appearance in each file
3. Process all `imports = [..]` statements just like C's `#include`

In the end, this provides a list of tasks to do outside of the rootfs itself and inside the rootfs.

TODO needs more explanation.

After parsing, the rootfs creation stage kicks off:
1. Run all `spawn` statements in order (on the host system)
2. Run all `init` statements in order (on the host system)
3. Run all `provision` statements in order (on the chrooted rootfs)
4. Run all `cleanup` statements in order (on the chrooted rootfs)
5. Run all `dispose` statements in order (on the host system)

Where the "host" system is not exactly the host system `rootfs-spawn` is running on. Currently it is, but it will be a `systemd-nspawn` container which has all the tools required plus the host system's rootfs mounted under `/mnt/host` and the target rootfs mounted under `/mnt/rootfs`. See [configs/defaults/debian/init](configs/defaults/debian/init) for example.

So the architecture will be something like this (all inside a special `systemd-nspawn` container):
1. Populate `/mnt/rootfs` via the given tool defined by `spawn` statements (i.e., `debootstrap`)
2. Execute the `init` statements
3. Run a nested and ephemeral `systemd-nspawn` container where `/mnt/rootfs` becomes its rootfs and execute the `provision` statements, after that the `cleanup` statements
4. Execute the `dispose` statements

TODO what about the `cache` config? We need a better way for that... it should probably become part of the `spawn` config.

TODO add default `dispose` configs

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
