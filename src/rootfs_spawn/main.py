import logging
import shutil
from pathlib import Path
from typing import Iterator

import defopt


PREREQUISITE_MAP: dict[str, list[Path]] = {
    "debian": [
        Path("debootstrap"),
    ],
    "archlinux": [Path("pacstrap")],
}
PREREQUISITE_MAP["ubuntu"] = PREREQUISITE_MAP["debian"]


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


def assert_prerequisites(executables: Iterator[Path]):
    for executable in executables:
        resolved_path = executable.as_posix()

        if shutil.which(resolved_path) is None:
            raise PrerequisiteNotExecutableError(
                f"The command 'which {resolved_path}' has failed!"
            )

        logger.info(
            f"Found prerequisite executable '{executable}' at '{resolved_path}'"
        )


# all args after the * are switches (i.e., -c, --count, -x)
# greeting: str, y: int, *, count: int = 1, x: str


def cli(distro: str):
    """
    Spawn a rootfs!

    :param distro: The distro mechanism to use to spawn the rootfs.
                   Supported distros: debian, ubuntu, archlinux
    """
    if distro not in PREREQUISITE_MAP:
        raise DistroNotSupportedError(distro)

    executables = iter(PREREQUISITE_MAP[distro])
    assert_prerequisites(executables)


def main():
    defopt.run(cli)


if __name__ == "__main__":
    main()
