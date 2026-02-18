from __future__ import annotations

import argparse
import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from importlib import metadata as importlib_metadata
except ImportError:  # pragma: no cover
    import importlib_metadata  # type: ignore

try:
    from dotenv import dotenv_values
except Exception:  # pragma: no cover
    dotenv_values = None  # type: ignore


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VENV_DIR = PROJECT_ROOT / ".venv"
VENV_PYTHON = VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
VENV_BIN_DIR = VENV_DIR / ("Scripts" if os.name == "nt" else "bin")
REQUIREMENTS_PATH = PROJECT_ROOT / "requirements.txt"
DOTENV_PATH = PROJECT_ROOT / ".env"
MIN_PYTHON = (3, 12)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

IMPORT_CHECKS: dict[str, str] = {
    "flask": "Flask",
    "flask_sqlalchemy": "Flask-SQLAlchemy",
    "flask_mail": "Flask-Mail",
    "flask_login": "Flask-Login",
    "sqlalchemy": "SQLAlchemy",
    "dotenv": "python-dotenv",
    "requests": "requests",
    "psycopg2": "psycopg2-binary",
    "pytest": "pytest",
    "langchain": "langchain",
    "langchain_core": "langchain-core",
    "langgraph": "langgraph",
    "langchain_openai": "langchain-openai",
    "langchain_community": "langchain-community",
    "supabase": "supabase",
    "tiktoken": "tiktoken",
    "bs4": "beautifulsoup4",
}

RUNTIME_ENV_KEYS = [
    "DATABASE_URL",
    "OPENAI_API_KEY",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
]

TOOL_FALLBACKS: dict[str, list[str]] = {
    "git": [
        r"D:\Git\cmd\git.exe",
        r"C:\Program Files\Git\cmd\git.exe",
        r"C:\Program Files (x86)\Git\cmd\git.exe",
    ],
    "bash": [
        r"D:\Git\bin\bash.exe",
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
    ],
    "gh": [
        r"C:\Program Files\GitHub CLI\gh.exe",
        r"C:\Program Files (x86)\GitHub CLI\gh.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\GitHub CLI\gh.exe"),
    ],
    "gcloud": [
        r"D:\Google Cloud SDK\google-cloud-sdk\bin\gcloud.cmd",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"),
        r"C:\Program Files\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd",
        r"C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd",
    ],
    "docker": [
        r"C:\Program Files\Docker\Docker\resources\bin\docker.exe",
    ],
}

TOOL_PROBE_ARGS: dict[str, list[str]] = {
    "git": ["--version"],
    "bash": ["--version"],
    "gh": ["--version"],
    "gcloud": ["--version"],
    "docker": ["--version"],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate project maintenance environment under .venv. "
            "Checks interpreter path, required packages, optional runtime env vars, and tool paths."
        )
    )
    parser.add_argument("--check-app-import", action="store_true")
    parser.add_argument("--require-runtime-env", action="store_true")
    parser.add_argument("--require-release-tools", action="store_true")
    parser.add_argument("--require-deploy-tools", action="store_true")
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def normalize_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").lower()


def same_path(a: Path, b: Path) -> bool:
    return normalize_path(a) == normalize_path(b)


def parse_requirement_name(line: str) -> str:
    value = line.strip()
    if not value or value.startswith("#"):
        return ""
    if value.startswith("-r") or value.startswith("--"):
        return ""

    value = value.split(";", 1)[0].strip()
    for marker in ("==", ">=", "<=", "~=", "!=", ">", "<"):
        idx = value.find(marker)
        if idx >= 0:
            value = value[:idx].strip()
            break
    if "[" in value:
        value = value.split("[", 1)[0].strip()
    return value


def read_required_distributions(path: Path) -> list[str]:
    if not path.exists():
        return []
    names: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        name = parse_requirement_name(raw)
        if name:
            names.append(name)
    return sorted(set(names))


def tool_is_usable(tool_name: str, tool_path: Path) -> bool:
    probe_args = TOOL_PROBE_ARGS.get(tool_name, ["--version"])
    try:
        completed = subprocess.run(
            [str(tool_path), *probe_args],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except Exception:
        return False
    return completed.returncode == 0


def find_tool(tool_name: str) -> Path | None:
    candidates: list[Path] = []

    found = shutil.which(tool_name)
    if found:
        candidates.append(Path(found))

    for candidate in TOOL_FALLBACKS.get(tool_name, []):
        expanded = Path(os.path.expandvars(candidate))
        if expanded.exists():
            candidates.append(expanded)

    seen: set[str] = set()
    for candidate in candidates:
        key = normalize_path(candidate)
        if key in seen:
            continue
        seen.add(key)
        if tool_is_usable(tool_name, candidate):
            return candidate
    return None


def load_dotenv_map() -> dict[str, str]:
    if dotenv_values is None or not DOTENV_PATH.exists():
        return {}
    parsed = dotenv_values(DOTENV_PATH) or {}
    result: dict[str, str] = {}
    for key, value in parsed.items():
        if key is None or value is None:
            continue
        result[str(key)] = str(value)
    return result


def env_status(key: str, dotenv_map: dict[str, str]) -> tuple[bool, str]:
    runtime_value = os.getenv(key, "").strip()
    if runtime_value:
        return True, "process env"
    dotenv_value = str(dotenv_map.get(key, "")).strip()
    if dotenv_value:
        return True, ".env"
    return False, "missing"


def main() -> int:
    args = parse_args()
    if args.strict:
        args.check_app_import = True
        args.require_runtime_env = True
        args.require_release_tools = True
        args.require_deploy_tools = True

    failures: list[str] = []
    warnings: list[str] = []
    oks: list[str] = []

    if not VENV_PYTHON.exists():
        failures.append(
            f".venv python missing: {VENV_PYTHON} (run: python -m venv .venv)"
        )
    else:
        oks.append(f".venv python exists: {VENV_PYTHON}")

    current_python = Path(sys.executable)
    if VENV_PYTHON.exists() and not same_path(current_python, VENV_PYTHON):
        failures.append(
            "Current interpreter is not project .venv python: "
            f"{current_python} (expected {VENV_PYTHON})"
        )
    else:
        oks.append(f"Using project .venv interpreter: {current_python}")

    if sys.version_info < MIN_PYTHON:
        failures.append(
            f"Python version too old: {sys.version_info.major}.{sys.version_info.minor} "
            f"(required >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]})"
        )
    else:
        oks.append(
            f"Python version OK: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        )

    missing_scripts: list[str] = []
    script_names = ["pip", "pytest", "flask"]
    for name in script_names:
        script_file = VENV_BIN_DIR / (f"{name}.exe" if os.name == "nt" else name)
        if not script_file.exists():
            missing_scripts.append(str(script_file))
    if missing_scripts:
        failures.append("Missing expected .venv entrypoints: " + ", ".join(missing_scripts))
    else:
        oks.append("Core .venv entrypoints found: pip/pytest/flask")

    required_distributions = read_required_distributions(REQUIREMENTS_PATH)
    missing_distributions: list[str] = []
    for dist_name in required_distributions:
        try:
            importlib_metadata.version(dist_name)
        except importlib_metadata.PackageNotFoundError:
            missing_distributions.append(dist_name)
    if missing_distributions:
        failures.append(
            "Missing distributions from requirements.txt: " + ", ".join(missing_distributions)
        )
    else:
        oks.append(
            f"All requirements.txt distributions installed ({len(required_distributions)} packages)"
        )

    missing_imports: list[str] = []
    for module_name, package_name in IMPORT_CHECKS.items():
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # pragma: no cover
            missing_imports.append(f"{module_name} ({package_name}): {exc}")
    if missing_imports:
        failures.append("Import check failures: " + " | ".join(missing_imports))
    else:
        oks.append(f"Import checks passed ({len(IMPORT_CHECKS)} modules)")

    dotenv_map = load_dotenv_map()
    for key in RUNTIME_ENV_KEYS:
        present, source = env_status(key, dotenv_map)
        if present:
            oks.append(f"{key} available ({source})")
        elif args.require_runtime_env:
            failures.append(f"Missing required runtime env key: {key}")
        else:
            warnings.append(f"Runtime env key missing (optional for this run): {key}")

    required_tools = ["git"]
    if args.require_release_tools:
        required_tools.extend(["gh", "bash"])
    if args.require_deploy_tools:
        required_tools.append("gcloud")

    optional_tools = []
    if not args.require_release_tools:
        optional_tools.extend(["gh", "bash"])
    if not args.require_deploy_tools:
        optional_tools.extend(["gcloud"])

    seen_tools: set[str] = set()
    for tool in required_tools:
        if tool in seen_tools:
            continue
        seen_tools.add(tool)
        resolved = find_tool(tool)
        if resolved is None:
            failures.append(f"Required tool not found: {tool}")
        else:
            oks.append(f"Tool found: {tool} -> {resolved}")

    for tool in optional_tools:
        if tool in seen_tools:
            continue
        seen_tools.add(tool)
        resolved = find_tool(tool)
        if resolved is None:
            warnings.append(f"Optional tool not found: {tool}")
        else:
            oks.append(f"Tool found: {tool} -> {resolved}")

    if args.check_app_import:
        try:
            from app import create_app

            create_app()
            oks.append("App import check passed: app.create_app()")
        except Exception as exc:
            failures.append(f"App import check failed: {exc}")

    print("=== VENV Doctor Report ===")
    print(f"Project root: {PROJECT_ROOT}")
    for line in oks:
        print(f"[OK] {line}")
    for line in warnings:
        print(f"[WARN] {line}")
    for line in failures:
        print(f"[FAIL] {line}")

    if failures:
        print(f"Result: FAILED ({len(failures)} issue(s))")
        return 1
    print("Result: PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
