"""The shipped skill remains self-contained and installs without losing edits."""
import importlib.util
from pathlib import Path
import re

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('install_skill', ROOT / 'app/scripts/install_skill.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def test_skill_frontmatter_metadata_and_local_references():
    root = installer.SOURCE
    text = (root / 'SKILL.md').read_text('utf-8')
    frontmatter = yaml.safe_load(text.split('---', 2)[1])
    assert frontmatter['name'] == root.name
    assert frontmatter['description'].strip()
    metadata = yaml.safe_load((root / 'agents/openai.yaml').read_text('utf-8'))
    assert 25 <= len(metadata['interface']['short_description']) <= 64
    assert '$' + root.name in metadata['interface']['default_prompt']
    for path in root.rglob('*.md'):
        for link in re.findall(r'\]\(([^)]+)\)', path.read_text('utf-8')):
            if '://' in link or link.startswith('#'):
                continue
            target = (path.parent / link.split('#')[0]).resolve()
            assert target.is_relative_to(root.resolve()) and target.is_file(), (path, link)


def test_installer_preserves_existing_custom_skill_and_is_idempotent(tmp_path):
    target = installer.install(tmp_path / 'skills')
    assert installer.files(target) == installer.files(installer.SOURCE)
    assert installer.install(tmp_path / 'skills') == target
    skill = target / 'SKILL.md'
    custom = skill.read_bytes() + b'\nLocal customization\n'
    skill.write_bytes(custom)
    with pytest.raises(ValueError, match='different skill'):
        installer.install(tmp_path / 'skills')
    assert skill.read_bytes() == custom
    alternate = installer.install(tmp_path / 'alternate')
    assert installer.files(alternate) == installer.files(installer.SOURCE)
