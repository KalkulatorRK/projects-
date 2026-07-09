import pytest

from backend.presets import INPUT_EXTENSIONS, PRESETS, get_preset, is_supported_input, list_presets


def test_input_extensions_include_vob_and_avi():
    assert '.vob' in INPUT_EXTENSIONS
    assert '.avi' in INPUT_EXTENSIONS
    assert '.mkv' in INPUT_EXTENSIONS


def test_presets_not_empty():
    assert len(PRESETS) >= 8


def test_list_presets_shape():
    items = list_presets()
    assert items[0]['id'] == 'mp4_h264'
    assert 'label' in items[0]
    assert 'extension' in items[0]


def test_get_preset_unknown():
    with pytest.raises(KeyError):
        get_preset('unknown_preset_xyz')


def test_is_supported_input():
    assert is_supported_input('movie.vob')
    assert is_supported_input('C:\\Videos\\test.AVI')
    assert not is_supported_input('document.pdf')


def test_mp4_h264_args():
    p = get_preset('mp4_h264')
    assert p.extension == '.mp4'
    assert 'libx264' in p.ffmpeg_args
    assert 'aac' in p.ffmpeg_args
