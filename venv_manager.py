import glob
import json
import os
import shlex
import shutil
import subprocess


class VenvError(Exception):
    pass


class PythonInstall:
    __slots__ = ("path", "version", "source")

    def __init__(self, path, version, source):
        self.path = path
        self.version = version
        self.source = source

    def __repr__(self):
        return f"PythonInstall({self.version}, {self.source}, {self.path})"

    def display_name(self):
        return f"Python {self.version} ({self.source})"


class VenvInfo:
    __slots__ = ("name", "path", "python_version", "python_home", "is_valid", "source")

    def __init__(self, name, path, python_version, python_home, is_valid, source):
        self.name = name
        self.path = path
        self.python_version = python_version
        self.python_home = python_home
        self.is_valid = is_valid
        self.source = source

    def __repr__(self):
        return f"VenvInfo({self.name}, {self.python_version}, {self.source})"


class PackageInfo:
    __slots__ = ("name", "version")

    def __init__(self, name, version):
        self.name = name
        self.version = version


SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".tox", ".nox",
    ".eggs", "dist", "build", ".mypy_cache", ".pytest_cache",
    "Library", "Applications", ".Trash", ".cache", ".npm",
    ".cargo", ".rustup", ".local", ".pyenv", ".nvm",
    "Pictures", "Music", "Movies", ".docker",
}


def detect_python_versions():
    candidates = []
    seen_realpaths = set()

    search_patterns = [
        ("/usr/bin/python3", "system"),
        ("/opt/homebrew/bin/python3", "homebrew"),
        ("/opt/homebrew/bin/python3.*[0-9]", "homebrew"),
        ("/usr/local/bin/python3", "homebrew"),
        ("/usr/local/bin/python3.*[0-9]", "homebrew"),
        ("/Library/Frameworks/Python.framework/Versions/*/bin/python3", "python.org"),
    ]

    pyenv_root = os.path.expanduser("~/.pyenv/versions")
    if os.path.isdir(pyenv_root):
        search_patterns.append((os.path.join(pyenv_root, "*/bin/python3"), "pyenv"))

    for pattern, source in search_patterns:
        if "*" in pattern or "." in pattern.split("/")[-1]:
            paths = sorted(glob.glob(pattern))
        else:
            paths = [pattern] if os.path.exists(pattern) else []

        for path in paths:
            realpath = os.path.realpath(path)
            if realpath in seen_realpaths:
                continue
            if not os.access(path, os.X_OK):
                continue

            try:
                result = subprocess.run(
                    [path, "--version"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    version_str = result.stdout.strip().replace("Python ", "")
                    seen_realpaths.add(realpath)
                    candidates.append(PythonInstall(path, version_str, source))
            except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError):
                continue

    candidates.sort(key=lambda p: _version_tuple(p.version), reverse=True)
    return candidates


def _version_tuple(version_str):
    try:
        return tuple(int(x) for x in version_str.split(".")[:3])
    except (ValueError, AttributeError):
        return (0, 0, 0)


def parse_pyvenv_cfg(venv_path):
    cfg_path = os.path.join(venv_path, "pyvenv.cfg")
    data = {}
    if not os.path.exists(cfg_path):
        return data
    try:
        with open(cfg_path, "r") as f:
            for line in f:
                line = line.strip()
                if "=" in line:
                    key, _, value = line.partition("=")
                    data[key.strip()] = value.strip()
    except IOError:
        pass
    return data


def _build_venv_info(dirpath, source="discovered"):
    cfg = parse_pyvenv_cfg(dirpath)
    if not cfg:
        return None

    python_bin = os.path.join(dirpath, "bin", "python")
    is_valid = os.path.isfile(python_bin) and os.access(python_bin, os.X_OK)

    version = cfg.get("version", cfg.get("version_info", "unknown"))
    python_home = cfg.get("home", "")

    return VenvInfo(
        name=os.path.basename(dirpath),
        path=os.path.abspath(dirpath),
        python_version=version,
        python_home=python_home,
        is_valid=is_valid,
        source=source,
    )


def discover_venvs(scan_dirs, max_depth=3):
    results = []
    seen_paths = set()

    for base_dir in scan_dirs:
        base_dir = os.path.expanduser(base_dir)
        if not os.path.isdir(base_dir):
            continue

        for dirpath, dirnames, filenames in os.walk(base_dir, followlinks=False):
            depth = dirpath[len(base_dir):].count(os.sep)
            if depth >= max_depth:
                dirnames.clear()
                continue

            dirnames[:] = [
                d for d in dirnames
                if d not in SKIP_DIRS and not d.startswith(".")
                or d in (".venv", ".env")
            ]

            if "pyvenv.cfg" in filenames:
                real = os.path.realpath(dirpath)
                if real not in seen_paths:
                    info = _build_venv_info(dirpath, source="discovered")
                    if info:
                        results.append(info)
                        seen_paths.add(real)
                dirnames.clear()

    return results


def load_managed_venvs(managed_paths):
    results = []
    for path in managed_paths:
        if os.path.isdir(path) and os.path.exists(os.path.join(path, "pyvenv.cfg")):
            info = _build_venv_info(path, source="managed")
            if info:
                results.append(info)
        else:
            results.append(VenvInfo(
                name=os.path.basename(path),
                path=path,
                python_version="unknown",
                python_home="",
                is_valid=False,
                source="managed (missing)",
            ))
    return results


def create_venv(path, python_path, with_pip=True, system_site_packages=False):
    cmd = [python_path, "-m", "venv", path]
    if not with_pip:
        cmd.append("--without-pip")
    if system_site_packages:
        cmd.append("--system-site-packages")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise VenvError(f"Failed to create venv:\n{result.stderr}")

    info = _build_venv_info(path, source="managed")
    if not info:
        raise VenvError("Venv created but pyvenv.cfg not found")
    return info


def delete_venv(path):
    cfg = os.path.join(path, "pyvenv.cfg")
    if not os.path.exists(cfg):
        raise VenvError(f"Safety check failed: {path} does not appear to be a virtual environment")
    shutil.rmtree(path)


def get_venv_python(venv_path):
    return os.path.join(venv_path, "bin", "python")


def list_packages(venv_path):
    venv_python = get_venv_python(venv_path)
    if not os.path.isfile(venv_python):
        return []

    try:
        result = subprocess.run(
            [venv_python, "-m", "pip", "list", "--format=json"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return []
        packages = json.loads(result.stdout)
        return [PackageInfo(p["name"], p["version"]) for p in packages]
    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError):
        return []


def install_package(venv_path, package_spec):
    venv_python = get_venv_python(venv_path)
    result = subprocess.run(
        [venv_python, "-m", "pip", "install", package_spec],
        capture_output=True, text=True, timeout=300
    )
    output = result.stdout + result.stderr
    if result.returncode != 0:
        raise VenvError(f"pip install failed:\n{output}")
    return output


def remove_package(venv_path, package_name):
    venv_python = get_venv_python(venv_path)
    result = subprocess.run(
        [venv_python, "-m", "pip", "uninstall", "-y", package_name],
        capture_output=True, text=True, timeout=60
    )
    output = result.stdout + result.stderr
    if result.returncode != 0:
        raise VenvError(f"pip uninstall failed:\n{output}")
    return output


def upgrade_package(venv_path, package_name):
    venv_python = get_venv_python(venv_path)
    result = subprocess.run(
        [venv_python, "-m", "pip", "install", "--upgrade", package_name],
        capture_output=True, text=True, timeout=300
    )
    output = result.stdout + result.stderr
    if result.returncode != 0:
        raise VenvError(f"pip upgrade failed:\n{output}")
    return output


def activate_in_terminal(venv_path):
    activate_path = os.path.join(venv_path, "bin", "activate")
    if not os.path.exists(activate_path):
        raise VenvError(f"Activate script not found: {activate_path}")

    script = (
        'tell application "Terminal"\n'
        f'    do script "source {shlex.quote(activate_path)}"\n'
        '    activate\n'
        'end tell'
    )
    subprocess.run(["/usr/bin/osascript", "-e", script], timeout=10)


def reveal_in_finder(path):
    subprocess.run(["open", "-R", path], timeout=5)
