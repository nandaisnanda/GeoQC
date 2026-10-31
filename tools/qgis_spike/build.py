"""Zip the plugin as geoqc_spike.zip (top-level folder geoqc_spike/)."""

import zipfile
from pathlib import Path

HERE = Path(__file__).parent
FILES = ("metadata.txt", "__init__.py", "plugin.py")


def main() -> None:
    target = HERE / "geoqc_spike.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            archive.write(HERE / name, f"geoqc_spike/{name}")
    print(target)


if __name__ == "__main__":
    main()
