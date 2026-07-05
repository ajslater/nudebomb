"""Tests for lang file discovery up the directory tree."""

from types import SimpleNamespace

from nudebomb.config.langfiles import LangFiles

__all__ = ()


def _make_langfiles() -> LangFiles:
    config = SimpleNamespace(languages=frozenset({"eng"}), symlinks=True)
    return LangFiles(config)  # pyright: ignore[reportArgumentType], # ty: ignore[invalid-argument-type]


def test_root_langs_file_applies_to_nested_dirs(tmp_path):
    """A langs sidecar in the top path applies to deeply nested files."""
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    (tmp_path / "langs").write_text("fra\n")

    langfiles = _make_langfiles()
    langs = langfiles.get_langs(tmp_path, nested)

    assert "fra" in langs
    assert "eng" in langs
    assert langfiles.found_lang_files(tmp_path, nested)


def test_root_langs_file_applies_to_top_dir(tmp_path):
    """A langs sidecar applies to files directly in the top path."""
    (tmp_path / "langs").write_text("fra\n")

    langfiles = _make_langfiles()
    langs = langfiles.get_langs(tmp_path, tmp_path)

    assert "fra" in langs
    assert langfiles.found_lang_files(tmp_path, tmp_path)


def test_intermediate_lang_file_applies_below(tmp_path):
    """Lang files at every ancestor level contribute languages."""
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    (tmp_path / "langs").write_text("fra\n")
    (tmp_path / "a" / "lang").write_text("ja\n")

    langfiles = _make_langfiles()
    langs = langfiles.get_langs(tmp_path, nested)

    assert {"eng", "fra", "jpn"} <= langs


def test_no_lang_files_found(tmp_path):
    nested = tmp_path / "a"
    nested.mkdir()

    langfiles = _make_langfiles()
    langs = langfiles.get_langs(tmp_path, nested)

    assert langs == frozenset({"eng"})
    assert not langfiles.found_lang_files(tmp_path, nested)


def test_lang_file_languages_normalized_to_alpha3(tmp_path):
    """Two-letter codes in lang files match alpha3 track languages."""
    (tmp_path / "langs").write_text("fr, de\n")

    langfiles = _make_langfiles()
    langs = langfiles.get_langs(tmp_path, tmp_path)

    assert {"fra", "deu"} <= langs


def test_get_extra_langs_excludes_base(tmp_path):
    """get_extra_langs returns only lang-file langs, not the base --languages."""
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    (tmp_path / "langs").write_text("fra\n")
    (tmp_path / "a" / "lang").write_text("ja\n")

    langfiles = _make_langfiles()
    extra = langfiles.get_extra_langs(tmp_path, nested)

    assert extra == frozenset({"fra", "jpn"})  # no "eng" base


def test_get_extra_langs_empty_without_files(tmp_path):
    """With no lang files, get_extra_langs contributes nothing."""
    nested = tmp_path / "a"
    nested.mkdir()

    langfiles = _make_langfiles()

    assert langfiles.get_extra_langs(tmp_path, nested) == frozenset()
