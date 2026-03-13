"""Tests for agent/utils/file_manager.py"""

from __future__ import annotations

import os
import tempfile

import pytest

from agent.utils.file_manager import (
    append_to_file,
    append_to_section,
    ensure_dir,
    get_section,
    now_str,
    read_file,
    replace_section,
    write_file,
)


# ── ensure_dir ────────────────────────────────────────────────────────────────

def test_ensure_dir_creates_directory(tmp_path):
    new_dir = str(tmp_path / "a" / "b" / "c")
    result = ensure_dir(new_dir)
    assert os.path.isdir(new_dir)
    assert result == new_dir


# ── read_file / write_file ────────────────────────────────────────────────────

def test_write_and_read_file(tmp_path):
    path = str(tmp_path / "test.txt")
    write_file(path, "hello world")
    assert read_file(path) == "hello world"


def test_read_file_default_when_absent(tmp_path):
    path = str(tmp_path / "nonexistent.txt")
    assert read_file(path) == ""
    assert read_file(path, default="fallback") == "fallback"


def test_append_to_file(tmp_path):
    path = str(tmp_path / "append.txt")
    write_file(path, "line1\n")
    append_to_file(path, "line2\n")
    assert read_file(path) == "line1\nline2\n"


# ── get_section ────────────────────────────────────────────────────────────────

def test_get_section_found():
    md = "# Title\n\n## Introduction\n\nSome intro text.\n\n## Methods\n\nMethods text."
    assert "Some intro text." in get_section(md, "Introduction")


def test_get_section_not_found():
    md = "# Title\n\n## Introduction\n\nText."
    assert get_section(md, "Missing") == ""


def test_get_section_case_insensitive():
    md = "## Introduction\n\nContent here."
    assert get_section(md, "introduction") != ""


# ── replace_section ───────────────────────────────────────────────────────────

def test_replace_section_existing():
    md = "## Intro\n\nOld content.\n\n## Other\n\nOther."
    result = replace_section(md, "Intro", "New content.")
    assert "New content." in result
    assert "Old content." not in result
    assert "Other." in result


def test_replace_section_creates_if_absent():
    md = "## Existing\n\nContent."
    result = replace_section(md, "New Section", "Brand new content.")
    assert "Brand new content." in result
    assert "New Section" in result


# ── append_to_section ─────────────────────────────────────────────────────────

def test_append_to_section():
    md = "## Notes\n\nFirst note."
    result = append_to_section(md, "Notes", "Second note.")
    assert "First note." in result
    assert "Second note." in result


def test_append_to_section_creates_if_absent():
    md = ""
    result = append_to_section(md, "NewSection", "Content.")
    assert "Content." in result


# ── now_str ───────────────────────────────────────────────────────────────────

def test_now_str_format():
    ts = now_str()
    import re
    assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", ts)
