# Projects: named collections of clip ids from the shared library.

import json

import pytest
from videogen import make_clip

from telltale.core.projects import FORMAT_VERSION, ProjectStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("TELLTALE_DATA_DIR", str(tmp_path / "data"))
    return ProjectStore()


def test_create_list_rename_delete(store):
    b = store.create("  Race   day 2 ")
    a = store.create("autumn series")
    assert b.name == "Race day 2"                       # tidied
    assert [p.name for p in store.all()] == ["autumn series", "Race day 2"]  # by name

    store.rename(b.id, "Race day 3")
    assert store.get(b.id).name == "Race day 3"

    store.delete(a.id)
    assert [p.id for p in store.all()] == [b.id]
    assert store.get(a.id) is None


def test_names_must_not_be_empty(store):
    with pytest.raises(ValueError):
        store.create("   ")
    p = store.create("ok")
    with pytest.raises(ValueError):
        store.rename(p.id, "")


def test_unique_name(store):
    assert store.unique_name() == "New project"
    store.create("New project")
    store.create("new project 2")
    assert store.unique_name() == "New project 3"


def test_add_and_remove_clips_keeps_order_without_duplicates(store):
    p = store.create("p")
    store.add_clips(p.id, ["c1", "c2"])
    store.add_clips(p.id, ["c2", "c3", "c1"])
    assert store.get(p.id).clip_ids == ["c1", "c2", "c3"]
    store.remove_clips(p.id, ["c2", "missing"])
    assert store.get(p.id).clip_ids == ["c1", "c3"]


def test_clip_shared_between_projects_and_forgotten(store):
    a, b, c = store.create("a"), store.create("b"), store.create("c")
    store.add_clips(a.id, ["shared", "x"])
    store.add_clips(b.id, ["shared"])
    assert {p.id for p in store.projects_using("shared")} == {a.id, b.id}

    store.forget_clip("shared")
    assert store.projects_using("shared") == []
    assert store.get(a.id).clip_ids == ["x"]
    assert store.get(c.id).clip_ids == []


def test_changes_update_modified_time_and_survive_reload(store, tmp_path):
    p = store.create("p")
    store.add_clips(p.id, ["c1"])
    reloaded = ProjectStore(store.root).get(p.id)
    assert reloaded.clip_ids == ["c1"] and reloaded.modified_at >= p.created_at
    saved = json.loads((p.path / "project.json").read_text())
    assert "folder" not in saved and saved["version"] == FORMAT_VERSION


def test_unknown_project_and_bad_files(store):
    with pytest.raises(KeyError):
        store.add_clips("nope", ["c1"])
    (store.root / "broken").mkdir()
    (store.root / "broken" / "project.json").write_text("{not json")
    newer = store.root / "future"
    newer.mkdir()
    (newer / "project.json").write_text(json.dumps(
        {"id": "future", "name": "From a newer app", "version": FORMAT_VERSION + 1}))
    assert store.all() == []                              # both skipped, no crash


def test_deleting_a_project_keeps_its_clips(store, library, videos):
    info = library.import_clip(make_clip(videos / "a.mp4", 320, 180, "25", 10))
    p = store.create("p")
    store.add_clips(p.id, [info.id])
    store.delete(p.id)
    assert library.get(info.id) is not None


def test_clip_size_is_recorded(library, videos):
    info = library.import_clip(make_clip(videos / "a.mp4", 320, 180, "25", 10))
    assert info.disk_bytes > 0
    assert library.size_on_disk(info.id) == info.disk_bytes
    assert library.total_size() == info.disk_bytes
