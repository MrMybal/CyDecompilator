"""Theme migration, actual ImGui styles and portable CyUI delivery."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
import cyui
import ui_common
from imgui_bundle import imgui


@pytest.mark.parametrize(('old', 'expected'), [('dark','navy'), ('light','light-grey'), ('classic','mid-grey'), ('invalid','navy')])
def test_existing_preferences_migrate_without_changing_file_or_language(tmp_path, old, expected):
    path = tmp_path / 'ui.json'
    original = json.dumps({'language':'fr', 'theme':old, 'font_scale':1.25})
    path.write_text(original)
    value = ui_common.Preferences(path)
    assert value.values['theme'] == expected and value.values['language'] == 'fr'
    assert value.values['font_scale'] == 1.25 and value.values['density'] == 'compact'
    assert path.read_text() == original
    value.save()
    assert ui_common.Preferences(path).values == value.values


def test_all_themes_styles_and_dpi_are_live_and_do_not_accumulate(monkeypatch, tmp_path):
    context = imgui.create_context()
    prefs = ui_common.Preferences(tmp_path / 'preferences.json')
    monkeypatch.setattr(ui_common, 'preferences', prefs)
    try:
        for key in ui_common.THEME_KEYS:
            prefs.values.update(theme=key, density='comfortable', font_scale=1.2)
            ui_common.apply_style()
            actual = imgui.get_style().color_(imgui.Col_.window_bg)
            expected = cyui.vec(cyui.palette().bg1)
            assert actual.x == pytest.approx(expected.x) and actual.y == pytest.approx(expected.y)
            assert cyui.is_light() == (key == 'light-grey')
            cyui.apply(key, 'comfortable', 1.5)
            size = imgui.get_style().frame_padding.x
            cyui.apply(key, 'comfortable', 1.5)
            assert imgui.get_style().frame_padding.x == size
            assert cyui.dp(20) == 30
            assert cyui.palette().text != cyui.palette().bg1
    finally:
        imgui.destroy_context(context)


def test_upstream_cyui_is_shipped_with_license_and_matching_source_hash():
    metadata = json.loads((APP / 'vendor/cyui-source.json').read_text('utf-8'))
    assert hashlib.sha256((APP / 'vendor/cyui.py').read_bytes()).hexdigest() == metadata['sha256']
    assert 'MIT License' in (APP / 'vendor/CYUI_LICENSE.txt').read_text('utf-8')
    assert {entry[0] for entry in cyui.THEMES} == set(ui_common.THEME_KEYS)
