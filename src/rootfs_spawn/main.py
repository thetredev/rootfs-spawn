import logging
import shutil
import sys
from pathlib import Path
from typing import Iterable, NamedTuple

import defopt
import pretty_errors
from plumbum import FG, local

from rootfs_spawn import parser
from rootfs_spawn.types import rootfs_spawn_config

pretty_errors.configure(
    full_line_newline=False,
    filename_display=pretty_errors.FILENAME_FULL,
    display_link=True,
    truncate_code=True,
    truncate_locals=True,
    display_arrow=True,
    exception_above=True,
)


class DistroNotSupportedError(Exception):
    pass


class PrerequisiteNotExecutableError(Exception):
    pass


def create_logger() -> logging.Logger:
    # create logger
    logger = logging.getLogger("pretty-logger")
    logger.setLevel(logging.INFO)

    # create console handler and set level to debug
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)

    # create formatter
    formatter = logging.Formatter(
        fmt="[rootfs-spawn] %(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # add formatter to ch
    ch.setFormatter(formatter)

    # add ch to logger
    logger.addHandler(ch)

    return logger


logger = create_logger()


def shell_command(arg0: str, *args: Iterable[str]) -> None:
    arg_string = " ".join(*args)
    logger.info("Executing shell command: %s %s", arg0, arg_string)

    command = local[arg0]
    _ = command[*args] & FG


def systemd_nspawn(
    procedure: str,
    rootfs_path: Path,
    *mounts: Iterable[str],
    private_users: str | None = "pick",
) -> None:
    rootfs_path_string = rootfs_path.as_posix()

    systemd_nspawn_arg0 = "systemd-nspawn"
    systemd_nspawn_args = [
        "--resolv-conf=replace-host",
        "--no-pager",
        "-D",
        rootfs_path_string,
        "--bind-ro=/:/mnt/host",
        *[f"--bind={mount}" for mount in mounts],
        "-q",
        "--",
        "/bin/bash",
        "-c",
        f"set -xe\n\ncd ~\n\n{procedure}",
    ]

    if private_users is not None:
        systemd_nspawn_args.insert(0, f"--private-users={private_users}")

    shell_command(systemd_nspawn_arg0, systemd_nspawn_args)


def parse_config(config_path: Path, search_path: Path) -> rootfs_spawn_config:
    statements = parser.parse(config_path.read_text(), search_path)
    config = parser.merge(statements)

    return config


def parse_block_kv(block: str) -> dict[str, str]:
    """Parse `key = value` lines from a block body, stripping inline comments."""
    result = {}
    for line in block.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip()
    return result


def parse_partition_spec(spec: str) -> tuple[str, str]:
    """Parse a `fstype,size` spec, e.g. `efi,1` or `xfs,all`."""
    fstype, _, size = spec.partition(",")
    return fstype.strip(), size.strip()


def sgdisk_size_arg(size: str) -> str:
    return "0" if size == "all" else f"+{size}G"


def find_free_nbd_device() -> str:
    for i in range(16):
        device = Path(f"/dev/nbd{i}")
        size_path = Path(f"/sys/class/block/nbd{i}/size")
        if device.exists() and size_path.exists() and size_path.read_text().strip() == "0":
            return device.as_posix()

    raise RuntimeError("No free /dev/nbdX device found; try 'modprobe nbd max_part=8'")


class VmMount(NamedTuple):
    image_path: Path
    nbd_device: str
    boot_fstype: str


def create_vm_rootfs(
    config: rootfs_spawn_config, rootfs_dir: Path, output_path: Path
) -> VmMount:
    """Create a disk image, partition/format it according to `disk`/`boot`/`root`,
    and mount the root (and boot) partitions at `rootfs_dir`."""

    disk_spec = parse_block_kv(str(config["disk"]))
    size_gib = disk_spec["size"]
    disk_format = disk_spec["format"]

    boot_fstype, boot_size = parse_partition_spec(disk_spec["boot"])
    root_fstype, root_size = parse_partition_spec(disk_spec["root"])

    image_path = output_path.parent / f"{output_path.name}.{disk_format}"

    logger.info("vm rootfs: creating disk image '%s' (%sGiB)", image_path, size_gib)
    shell_command(
        "qemu-img", ["create", "-f", disk_format, image_path.as_posix(), f"{size_gib}G"]
    )

    nbd_device = find_free_nbd_device()
    logger.info("vm rootfs: attaching disk image via '%s'", nbd_device)
    shell_command("qemu-nbd", ["-c", nbd_device, "-f", disk_format, image_path.as_posix()])

    logger.info("vm rootfs: partitioning disk")
    shell_command(
        "sgdisk",
        ["-n", f"1:0:{sgdisk_size_arg(boot_size)}", "-t", "1:ef00", nbd_device],
    )
    shell_command(
        "sgdisk",
        ["-n", f"2:0:{sgdisk_size_arg(root_size)}", "-t", "2:8300", nbd_device],
    )
    shell_command("partprobe", [nbd_device])

    boot_partition = f"{nbd_device}p1"
    root_partition = f"{nbd_device}p2"

    logger.info("vm rootfs: formatting boot partition as '%s'", boot_fstype)
    shell_command("mkfs.vfat", ["-F32", boot_partition])

    logger.info("vm rootfs: formatting root partition as '%s'", root_fstype)
    shell_command(f"mkfs.{root_fstype}", [root_partition])

    rootfs_dir_string = rootfs_dir.as_posix()
    logger.info("vm rootfs: mounting root partition at '%s'", rootfs_dir_string)
    shell_command("mount", [root_partition, rootfs_dir_string])

    boot_dir = rootfs_dir / "boot"
    boot_dir.mkdir(parents=True, exist_ok=True)
    logger.info("vm rootfs: mounting boot partition at '%s'", boot_dir.as_posix())
    shell_command("mount", [boot_partition, boot_dir.as_posix()])

    return VmMount(image_path=image_path, nbd_device=nbd_device, boot_fstype=boot_fstype)


def install_vm_bootloader(
    config: rootfs_spawn_config, rootfs_dir: Path, vm_mount: VmMount
) -> None:
    bootloader = config.get("bootloader")
    if bootloader is None:
        return

    if bootloader == "systemd-boot" and vm_mount.boot_fstype == "efi":
        logger.info("vm rootfs: installing systemd-boot")
        systemd_nspawn("bootctl install --esp-path=/boot", rootfs_dir)
    else:
        raise ValueError(f"Unsupported bootloader '{bootloader}' for boot type '{vm_mount.boot_fstype}'")


def teardown_vm_rootfs(rootfs_dir: Path, vm_mount: VmMount) -> None:
    logger.info("vm rootfs: unmounting boot and root partitions")
    shell_command("umount", [(rootfs_dir / "boot").as_posix()])
    shell_command("umount", [rootfs_dir.as_posix()])

    logger.info("vm rootfs: detaching disk image from '%s'", vm_mount.nbd_device)
    shell_command("qemu-nbd", ["-d", vm_mount.nbd_device])


def create_ctl(search_path: Path) -> Path:
    config_rootfs = search_path / "ctl.rootfs"
    output_path = Path("/var/lib/machines/rootfs-spawn-ctl")

    logger.info(
        "Creating rootfs-spawn-ctl rootfs at '%s' using search path '%s'",
        output_path.resolve().as_posix(),
        search_path.resolve().as_posix(),
    )

    config = parse_config(config_rootfs, search_path)

    if not output_path.exists():
        logger.info("ctl rootfs: running SPAWN procedure")
        spawn_proc_args = f"{config['spawn']} {output_path}".split(" ")
        spawn_proc_arg0 = spawn_proc_args.pop(0)

        shell_command(spawn_proc_arg0, spawn_proc_args)

    logger.info("ctl rootfs: running INIT procedure")
    systemd_nspawn(str(config["init"]), output_path, f"{output_path}:/mnt/rootfs")

    logger.info("ctl rootfs: running PROVISION procedure")
    systemd_nspawn(str(config["provision"]), output_path)

    logger.info("ctl rootfs: running CLEANUP procedure")
    systemd_nspawn(str(config["cleanup"]), output_path)

    return output_path


def cli_create(
    config_path: Path,
    output_path: Path = Path("output"),
    search_path: Path = Path.cwd(),
    *,
    force: bool = False,
) -> None:
    """
    Spawn a rootfs!

    :param config_path: A config file to use for bootstrapping the rootfs.
                   A stanza file can be initialized via `rootfs-spawn config <distro> <name>`

    :param output_path: The path to spawn the rootfs in.

    :param search_path: Base directory for resolving imports.
                        Defaults to the config file's parent directory.

    :param force: Indicates whether or not to recursively remove `output_path`
                  before populating it via the bootstrapper if it already exists,
                  without asking first.
    """

    rootfs_dir = output_path.resolve()
    rootfs_dir_string = rootfs_dir.as_posix()
    config = parse_config(config_path, search_path)

    if rootfs_dir.exists() and not force:
        if not (
            input(f"rootfs_dir '{rootfs_dir}' already exists! Remove it? [y/n]: ")
            .strip()
            .startswith(("y", "Y"))
        ):
            logger.error("`rootfs_dir` '%s' already exists!", rootfs_dir_string)
            logger.error("Aborting `spawn` procedure!")
            sys.exit(1)

    if rootfs_dir.exists():
        logger.info("Removing rootfs_dir '%s'", rootfs_dir_string)
        shutil.rmtree(rootfs_dir)

    rootfs_dir.mkdir(parents=True, exist_ok=False)

    vm_mount = None
    if config.get("type") == "vm":
        logger.info("target rootfs: type 'vm', provisioning disk image")
        vm_mount = create_vm_rootfs(config, rootfs_dir, output_path)

    ctl_output_path = create_ctl(search_path)
    logger.info("Successfully created rootfs-spawn-ctl rootfs.")
    logger.info(
        "Spawning the target rootfs using rootfs-spawn-ctl and rootfs config: %s",
        rootfs_dir_string,
    )

    packages_cache_dir = str(config["packages_cache_dir"])
    Path(packages_cache_dir).mkdir(parents=True, exist_ok=True)

    logger.info("target rootfs: running SPAWN procedure")
    spawn_command = f"{config['spawn']} /mnt/rootfs"
    systemd_nspawn(
        spawn_command,
        ctl_output_path,
        f"{rootfs_dir_string}:/mnt/rootfs",
        f"{packages_cache_dir}:{packages_cache_dir}",
        private_users=None,
    )

    logger.info("target rootfs: running INIT procedure")
    systemd_nspawn(
        str(config["init"]),
        rootfs_dir,
        f"{rootfs_dir_string}:/mnt/rootfs",
    )

    logger.info("target rootfs: running PROVISION procedure")
    systemd_nspawn(str(config["provision"]), rootfs_dir)

    logger.info("target rootfs: running CLEANUP procedure")
    systemd_nspawn(str(config["cleanup"]), rootfs_dir)

    if vm_mount is not None:
        install_vm_bootloader(config, rootfs_dir, vm_mount)
        teardown_vm_rootfs(rootfs_dir, vm_mount)
        logger.info("target rootfs: vm disk image created at '%s'", vm_mount.image_path)


def cli_config(distro: str, name: str) -> None:
    """
    Generate a config file to spawn a rootfs with.

    :param distro: The distro to set in the configuration.
                   Supported distros: debian, ubuntu, archlinux

    :param name: The name of the config file to write to disk as <name>.rootfs
    """
    pass


def main():
    defopt.run({"create": cli_create, "config": cli_config})


if __name__ == "__main__":
    main()
