import logging
import shutil
import sys
from pathlib import Path
from typing import Iterable

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


PREREQUISITE_MAP: dict[str, list[Path]] = {
    "debian": [
        Path("debootstrap"),
    ],
    "archlinux": [Path("pacstrap")],
}
# PREREQUISITE_MAP["ubuntu"] = PREREQUISITE_MAP["debian"]


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
    command = local[arg0]
    _ = command[*args] & FG


def spawn_procedure(config: rootfs_spawn_config, output_path: Path) -> None:
    spawn_proc_args = f"{config['spawn']} {output_path}".split(" ")
    spawn_proc_arg0 = spawn_proc_args.pop(0)

    shell_command(spawn_proc_arg0, spawn_proc_args)


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


def create_ctl(search_path: Path) -> Path:
    config_rootfs = search_path / "ctl.rootfs"
    output_path = Path("/var/lib/machines/rootfs-spawn-ctl")

    config = parse_config(config_rootfs, search_path)

    if not output_path.exists():
        spawn_procedure(config, output_path)

    systemd_nspawn(str(config["init"]), output_path, f"{output_path}:/mnt/rootfs")
    systemd_nspawn(str(config["provision"]), output_path)
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
        shutil.rmtree(rootfs_dir)
    rootfs_dir.mkdir(parents=True, exist_ok=False)

    ctl_output_path = create_ctl(search_path)

    packages_cache_dir = str(config["packages_cache_dir"])
    Path(packages_cache_dir).mkdir(parents=True, exist_ok=True)

    spawn_command = f"{config['spawn']} /mnt/rootfs"
    systemd_nspawn(
        spawn_command,
        ctl_output_path,
        f"{rootfs_dir_string}:/mnt/rootfs",
        f"{packages_cache_dir}:{packages_cache_dir}",
        private_users=None,
    )

    systemd_nspawn(
        str(config["init"]),
        rootfs_dir,
        f"{rootfs_dir_string}:/mnt/rootfs",
    )
    systemd_nspawn(str(config["provision"]), rootfs_dir)
    systemd_nspawn(str(config["cleanup"]), rootfs_dir)


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
