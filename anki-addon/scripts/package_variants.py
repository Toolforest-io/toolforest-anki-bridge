#!/usr/bin/env python3
"""Build and optionally install prod/test/dev Toolforest Bridge add-on variants."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = REPO_ROOT / "anki-addon" / "src" / "toolforest_bridge"
DIST_DIR = REPO_ROOT / "dist"
ANKI_ADDONS_DIR = Path.home() / "Library" / "Application Support" / "Anki2" / "addons21"


@dataclass(frozen=True)
class Variant:
    package: str
    name: str
    endpoint_override: str | None
    outfile: str


VARIANTS = [
    Variant(
        package="toolforest_bridge",
        name="Toolforest Bridge",
        endpoint_override=None,
        outfile="toolforest_bridge_prod.ankiaddon",
    ),
    Variant(
        package="toolforest_bridge_test",
        name="Toolforest Bridge (Test)",
        endpoint_override="wss://bridge-test.toolforest.io",
        outfile="toolforest_bridge_test.ankiaddon",
    ),
    Variant(
        package="toolforest_bridge_dev",
        name="Toolforest Bridge (Dev)",
        endpoint_override="wss://bridge-dev.toolforest.io",
        outfile="toolforest_bridge_dev.ankiaddon",
    ),
]


def patch_variant(staging: Path, variant: Variant) -> None:
    manifest_path = staging / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["package"] = variant.package
    manifest["name"] = variant.name
    manifest_path.write_text(json.dumps(manifest, indent=4) + "\n")

    config_path = staging / "config.json"
    config = json.loads(config_path.read_text())
    config["bridge_token"] = None
    config["bridge_device_id"] = None
    config["endpoint_override"] = variant.endpoint_override
    config_path.write_text(json.dumps(config, indent=4) + "\n")

    if variant.name != "Toolforest Bridge":
        ui_path = staging / "ui.py"
        ui_text = ui_path.read_text()
        ui_text = ui_text.replace("Toolforest Bridge", variant.name)
        ui_path.write_text(ui_text)


def clean_staging(staging: Path) -> None:
    for path in staging.rglob("__pycache__"):
        if path.is_dir():
            shutil.rmtree(path)
    for path in staging.rglob("*.pyc"):
        path.unlink()
    meta_path = staging / "meta.json"
    if meta_path.exists():
        meta_path.unlink()


def build_variant(variant: Variant) -> Path:
    DIST_DIR.mkdir(exist_ok=True)
    out = DIST_DIR / variant.outfile
    if out.exists():
        out.unlink()

    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / variant.package
        shutil.copytree(SOURCE_DIR, staging)
        clean_staging(staging)
        patch_variant(staging, variant)
        subprocess.run(["zip", "-r", "-q", str(out), "."], cwd=staging, check=True)
    return out


def install_variant(variant: Variant) -> None:
    target = ANKI_ADDONS_DIR / variant.package
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(SOURCE_DIR, target)
    clean_staging(target)
    patch_variant(target, variant)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--install",
        choices=["all", "nonprod"],
        help="Install variants into Anki addons21. Use nonprod to leave the prod add-on untouched.",
    )
    args = parser.parse_args()

    for variant in VARIANTS:
        out = build_variant(variant)
        print(f"Built {out}")
        should_install = args.install == "all" or (
            args.install == "nonprod" and variant.package != "toolforest_bridge"
        )
        if should_install:
            install_variant(variant)
            print(f"Installed {variant.name} to {ANKI_ADDONS_DIR / variant.package}")


if __name__ == "__main__":
    main()
