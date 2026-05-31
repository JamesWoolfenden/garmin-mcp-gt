"""
Release script: bumps version, builds, uploads to PyPI, commits and tags.
Usage: python release.py [major|minor|patch]  (default: patch)
"""

import re
import subprocess
import sys
from pathlib import Path

PYPROJECT = Path(__file__).parent / "pyproject.toml"


def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, check=True)
    if result.returncode != 0:
        sys.exit(result.returncode)


def bump_version(current: str, part: str) -> str:
    major, minor, patch = map(int, current.split("."))
    if part == "major":
        return f"{major + 1}.0.0"
    elif part == "minor":
        return f"{major}.{minor + 1}.0"
    else:
        return f"{major}.{minor}.{patch + 1}"


def main() -> None:
    part = sys.argv[1] if len(sys.argv) > 1 else "patch"
    if part not in ("major", "minor", "patch"):
        print(f"Unknown part '{part}'. Use major, minor, or patch.")
        sys.exit(1)

    text = PYPROJECT.read_text()
    match = re.search(r'^version = "(\d+\.\d+\.\d+)"', text, re.MULTILINE)
    if not match:
        print("Could not find version in pyproject.toml")
        sys.exit(1)

    current = match.group(1)
    new = bump_version(current, part)
    print(f"Bumping {current} -> {new}")

    PYPROJECT.write_text(text.replace(f'version = "{current}"', f'version = "{new}"'))

    # Clean old dist
    for f in Path("dist").glob("*") if Path("dist").exists() else []:
        f.unlink()

    run([sys.executable, "-m", "build"])
    run([sys.executable, "-m", "twine", "upload", "dist/*"])

    run(["git", "add", "pyproject.toml"])
    run(["git", "commit", "-m", f"Release v{new}"])
    run(["git", "tag", f"v{new}"])
    run(["git", "push"])
    run(["git", "push", "origin", f"v{new}"])

    print(f"\nReleased v{new}")


if __name__ == "__main__":
    main()
