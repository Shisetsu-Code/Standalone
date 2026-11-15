"""Package the installed Windows HTTP runtime for the Red Tiger executable."""
import argparse
import gzip
import importlib.util
from pathlib import Path
import struct
import sys
import zipfile


PACKAGES = ("requests", "urllib3", "certifi", "idna", "charset_normalizer")
OMIT = {"site-packages", "__pycache__", "test", "tests", "tkinter", "turtledemo", "idlelib", "ensurepip"}


def archive(output):
    root = Path(sys.base_prefix)
    version = f"python{sys.version_info.major}{sys.version_info.minor}"
    entries = {"python.exe": Path(sys.executable)}
    for path in root.glob("*.dll"):
        entries[path.name] = path
    for path in (root / "DLLs").glob("*"):
        if path.is_file() and path.suffix.lower() in (".pyd", ".dll"):
            entries[f"DLLs/{path.name}"] = path
    with gzip.open(output, "xb") as stream:
        def add(name, data):
            key = name.encode("utf-8")
            stream.write(struct.pack("<II", len(key), len(data)))
            stream.write(key)
            stream.write(data)

        for name, path in sorted(entries.items()):
            add(name, path.read_bytes())
        add(version + "._pth", b".\nDLLs\npython.zip\n")
        import io
        packages = io.BytesIO()
        with zipfile.ZipFile(packages, "w") as lib:
            for path in sorted((root / "Lib").rglob("*.py")):
                relative = path.relative_to(root / "Lib")
                if not OMIT.intersection(relative.parts):
                    lib.write(path, relative.as_posix())
            for name in PACKAGES:
                spec = importlib.util.find_spec(name)
                if spec is None or spec.origin is None:
                    raise ValueError(f"missing HTTP dependency: {name}")
                package = Path(spec.origin).parent
                for path in sorted(package.rglob("*")):
                    if path.is_file() and path.suffix in (".py", ".pem") and not OMIT.intersection(path.relative_to(package).parts):
                        lib.write(path, name + "/" + path.relative_to(package).as_posix())
        add("python.zip", packages.getvalue())
        add("redtiger_http.py", Path(__file__).with_name("redtiger_http_process.py").read_bytes())
        stream.write(struct.pack("<I", 0))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    options = parser.parse_args()
    if sys.platform != "win32":
        parser.error("the bundle must be built with the Windows Python interpreter")
    archive(options.output)
