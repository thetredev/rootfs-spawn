import logging
import shutil
from pathlib import Path
from typing import Iterator

import defopt
from plumbum import local, FG

from rootfs_spawn.parser import parse as parse_dsl


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


# all args after the * are switches (i.e., -c, --count, -x)
# greeting: str, y: int, *, count: int = 1, x: str


def cli_create(distro: str, config: str, rootfs_dir: str = "output"):
    """
    Spawn a rootfs!

    :param distro: The distro mechanism to use to spawn the rootfs.
                   Supported distros: debian, ubuntu, archlinux

    :param config: A config file to use for bootstrapping the rootfs.
                   A stanza file can be initialized via `rootfs-spawn config <distro> <name>`

    :param rootfs_dir: The path to spawn the rootfs in.
    """
    config_text = Path(config).read_text()
    result = parse_dsl(config_text)

    spawn_command_args = f"{result['spawn']} {rootfs_dir}".split(" ")
    spawn_command_arg0 = spawn_command_args.pop(0)

    packages_cache_dir = result["packages_cache_dir"]

    Path(packages_cache_dir).mkdir(parents=True, exist_ok=True)
    shutil.rmtree(rootfs_dir, ignore_errors=True)

    spawn_command = local[spawn_command_arg0]
    _ = spawn_command[*spawn_command_args] & FG

    # if distro not in PREREQUISITE_MAP:
    #     raise DistroNotSupportedError(distro)

    # executables = PREREQUISITE_MAP[distro]
    # resolved_executable_paths = list(assert_prerequisites(iter(executables)))
    # assert len(executables) == len(resolved_executable_paths)


def cli_config(distro: str, name: str):
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
