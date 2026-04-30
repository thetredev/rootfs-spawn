import shutil
from pathlib import Path
from typing import Iterator

import defopt


PREREQUISITE_MAP: dict[str, list[Path]] = {
    "debian": [
        Path("debootstrap"),
    ],
    "archlinux": [
        Path("pacstrap")
    ]
}
PREREQUISITE_MAP["ubuntu"] = PREREQUISITE_MAP["debian"]


class DistroNotSupportedError(Exception):
    pass


class PrerequisiteNotExecutableError(Exception):
    pass


def assert_prerequisites(executables: Iterator[Path]):
    for executable in executables:
        resolved_path = executable.as_posix()

        if shutil.which(resolved_path) is None:
            raise PrerequisiteNotExecutableError(f"The command 'which {resolved_path}' has failed!")


# all args after the * are switches (i.e., -c, --count, -x)
#greeting: str, y: int, *, count: int = 1, x: str

def cli(distro: str):
    """
    Spawn a rootfs!

    :param distro: The distro mechanism to use to spawn the rootfs.
                   Supported distros: debian, ubuntu, archlinux
    """
    if distro not in PREREQUISITE_MAP:
        raise DistroNotSupportedError(distro)

    executables = PREREQUISITE_MAP[distro]
    assert_prerequisites(iter(executables))


def main():
    defopt.run(cli)


if __name__ == "__main__":
    main()
