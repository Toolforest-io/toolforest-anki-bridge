import importlib.util
import sys
from pathlib import Path


def _load_package_variants():
    path = Path(__file__).resolve().parents[1] / "scripts" / "package_variants.py"
    spec = importlib.util.spec_from_file_location("package_variants", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_install_variant_preserves_existing_config_and_meta(monkeypatch, tmp_path):
    package_variants = _load_package_variants()
    source = tmp_path / "source"
    source.mkdir()
    (source / "manifest.json").write_text(
        '{"package": "toolforest_bridge", "name": "Toolforest Bridge"}\n'
    )
    (source / "config.json").write_text(
        '{"bridge_token": null, "endpoint_override": null}\n'
    )

    addons_dir = tmp_path / "addons"
    target = addons_dir / "toolforest_bridge"
    target.mkdir(parents=True)
    existing_config = '{"bridge_token": "saved-token"}\n'
    existing_meta = '{"config": {"bridge_device_id": "saved-device"}}\n'
    (target / "config.json").write_text(existing_config)
    (target / "meta.json").write_text(existing_meta)

    monkeypatch.setattr(package_variants, "SOURCE_DIR", source)
    monkeypatch.setattr(package_variants, "ANKI_ADDONS_DIR", addons_dir)

    package_variants.install_variant(package_variants.VARIANTS[0])

    assert (target / "manifest.json").read_text() == (
        '{\n'
        '    "package": "toolforest_bridge",\n'
        '    "name": "Toolforest Bridge"\n'
        '}\n'
    )
    assert (target / "config.json").read_text() == existing_config
    assert (target / "meta.json").read_text() == existing_meta
