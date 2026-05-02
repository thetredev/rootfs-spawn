import logging
import shutil
from pathlib import Path
from typing import Iterator

import pretty_errors
import defopt
from plumbum import local, FG

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


def assert_prerequisites(executables: Iterator[Path]) -> Iterator[Path]:
    for executable in executables:
        posix_path = executable.as_posix()
        resolved_path = shutil.which(posix_path)

        if resolved_path is None:
            raise PrerequisiteNotExecutableError(
                f"The command 'which {posix_path}' has failed!"
            )

        yield Path(resolved_path)
        logger.info(
            f"Found prerequisite executable '{executable}' at '{resolved_path}'"
        )


def shell_command(arg0: str, *args: list[str]) -> None:
    command = local[arg0]
    _ = command[*args] & FG


def spawn_procedure(config: rootfs_spawn_config, output_path: Path) -> None:
    # create packages cache dir
    packages_cache_dir = str(config["packages_cache_dir"])
    Path(packages_cache_dir).mkdir(parents=True, exist_ok=True)

    # run "spawn" procedure
    spawn_proc_args = f"{config['spawn']} {output_path}".split(" ")
    spawn_proc_arg0 = spawn_proc_args.pop(0)

    shutil.rmtree(output_path, ignore_errors=True)
    shell_command(spawn_proc_arg0, spawn_proc_args)


def systemd_nspawn(procedure: str, ctl_rootfs_path: Path, rootfs_path: Path) -> None:
    ctl_rootfs_path_string = ctl_rootfs_path.as_posix()
    rootfs_path_string = rootfs_path.as_posix()

    systemd_nspawn_arg0 = "systemd-nspawn"
    systemd_nspawn_args = [
        "--resolv-conf=replace-host",
        "--no-pager",
        "--private-users=pick",
        "-D",
        ctl_rootfs_path_string,
        "--bind-ro=/:/mnt/host",
        f"--bind={rootfs_path_string}:/mnt/rootfs",
        "-q",
        "--pipe",
        "--",
        "/bin/bash",
        "-c",
        f"<<EOFFFFFF\n{procedure}\nEOFFFFFF",
    ]

    print(" ".join(systemd_nspawn_args))
    shell_command(systemd_nspawn_arg0, systemd_nspawn_args)


def systemd_nspawn_nested(
    child_procedure: str, ctl_rootfs_path: Path, rootfs_path: Path
) -> None:
    procedure = f"systemd-nspawn -D /mnt/rootfs -q --ephemeral -- /bin/bash -c {child_procedure}"
    systemd_nspawn(procedure, ctl_rootfs_path, rootfs_path)


# all args after the * are switches (i.e., -c, --count, -x)
# greeting: str, y: int, *, count: int = 1, x: str


def cli_create(
    config: Path, output: Path = Path("output"), search_path: Path = Path.cwd()
) -> None:
    """
    Spawn a rootfs!

    :param config: A config file to use for bootstrapping the rootfs.
                   A stanza file can be initialized via `rootfs-spawn config <distro> <name>`

    :param rootfs_dir: The path to spawn the rootfs in.

    :param search_path: Base directory for resolving imports.
                        Defaults to the config file's parent directory.
    """
    ctl_rootfs = search_path / "ctl.rootfs"
    ctl_output_path = Path("/var/lib/machines/rootfs-spawn-ctl")

    statements = parser.parse(ctl_rootfs.read_text(), search_path)
    ctl_config = parser.merge(statements)

    # output_path = output.resolve()

    spawn_procedure(ctl_config, ctl_output_path)
    print("INIT")
    print("-----------------------------------------------")
    systemd_nspawn(str(ctl_config["init"]), ctl_output_path, ctl_output_path)
    print("PROVISION")
    print("-----------------------------------------------")
    systemd_nspawn_nested(
        str(ctl_config["provision"]), ctl_output_path, ctl_output_path
    )
    print("-----------------------------------------------")
    print("CLEANUP")
    print("-----------------------------------------------")
    systemd_nspawn_nested(str(ctl_config["cleanup"]), ctl_output_path, ctl_output_path)
    print("-----------------------------------------------")

    # if distro not in PREREQUISITE_MAP:
    #     raise DistroNotSupportedError(distro)

    # executables = PREREQUISITE_MAP[distro]
    # resolved_executable_paths = list(assert_prerequisites(iter(executables)))
    # assert len(executables) == len(resolved_executable_paths)


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
