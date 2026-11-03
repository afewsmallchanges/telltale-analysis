# Scenes: saved views of 1-4 of a project's clips.

import json

import pytest

from telltale.core.projects import FORMAT_VERSION, ProjectStore, Scene, SceneSlot


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("TELLTALE_DATA_DIR", str(tmp_path / "data"))
    return ProjectStore()


def test_new_scenes_are_numbered_and_start_empty(store):
    p = store.create("Race day")
    s1 = store.create_scene(p.id)
    s2 = store.create_scene(p.id)
    assert (s1.name, s2.name) == ("Scene 1", "Scene 2")
    assert s1.views == 1 and s1.slots == [None]          # one empty view (shows +)
    store.rename_scene(p.id, s1.id, "Start")
    s3 = store.create_scene(p.id)
    assert s3.name == "Scene 1"                          # free again after rename
    assert [s.name for s in store.get(p.id).scenes] == ["Start", "Scene 2", "Scene 1"]


def test_scene_with_clips_adds_them_to_the_project_max_four(store):
    p = store.create("p", clip_ids=["a"])
    s = store.create_scene(p.id, ["a", "b", "c", "d", "e"], name="Gybe")
    assert s.views == 4 and s.clip_ids() == ["a", "b", "c", "d"]
    assert store.get(p.id).clip_ids == ["a", "b", "c", "d"]


def test_save_scene_round_trip(store):
    p = store.create("p")
    s = store.create_scene(p.id)
    s.views = 2
    s.slots = [SceneSlot("a", offset="-3/25", crop=[10.0, 20.0, 640.0, 360.0]), None]
    s.time = "12/5"
    s.active = 1
    store.save_scene(p.id, s)

    back = store.get_scene(p.id, s.id)
    assert back.views == 2 and back.active == 1 and back.time == "12/5"
    assert back.slots[0] == SceneSlot("a", "-3/25", [10.0, 20.0, 640.0, 360.0])
    assert back.slots[1] is None
    assert "a" in store.get(p.id).clip_ids               # saving adds clips to the project


def test_removing_a_clip_from_the_project_empties_its_views(store):
    p = store.create("p")
    s = store.create_scene(p.id, ["a", "b"])
    assert [x.name for x in store.scenes_using(p.id, ["b"])] == [s.name]
    store.remove_clips(p.id, ["b"])
    back = store.get_scene(p.id, s.id)
    assert back.clip_ids() == ["a"] and back.views == 2 and back.slots[1] is None


def test_forgetting_a_clip_clears_it_from_every_project_and_scene(store):
    p, q = store.create("p"), store.create("q")
    store.create_scene(p.id, ["x", "y"])
    store.create_scene(q.id, ["x"])
    store.forget_clip("x")
    assert all("x" not in s.clip_ids() for pr in store.all() for s in pr.scenes)
    assert store.projects_using("x") == []


def test_delete_scene_keeps_clips(store):
    p = store.create("p")
    s = store.create_scene(p.id, ["a"])
    store.delete_scene(p.id, s.id)
    assert store.get(p.id).scenes == [] and store.get(p.id).clip_ids == ["a"]
    with pytest.raises(KeyError):
        store.rename_scene(p.id, s.id, "x")
    with pytest.raises(KeyError):
        store.save_scene(p.id, s)                        # deleted scenes aren't brought back


def test_version_1_projects_still_load(store):
    folder = store.root / "old"
    folder.mkdir()
    (folder / "project.json").write_text(json.dumps(
        {"id": "old", "name": "Before scenes", "clip_ids": ["a", "b"], "version": 1}))
    p = store.get("old")
    assert p.name == "Before scenes" and p.clip_ids == ["a", "b"] and p.scenes == []
    store.create_scene("old", ["a"])
    assert json.loads((folder / "project.json").read_text())["version"] == FORMAT_VERSION


def test_damaged_scene_data_is_tidied_on_load(store):
    folder = store.root / "odd"
    folder.mkdir()
    (folder / "project.json").write_text(json.dumps({
        "id": "odd", "name": "Odd", "version": 2,
        "scenes": [{"id": "s", "name": "S", "views": 9, "active": 7,
                    "slots": [{"clip_id": "a"}], "unknown": 1}]}))
    s = store.get("odd").scenes[0]
    assert isinstance(s, Scene) and s.views == 4 and len(s.slots) == 4 and s.active == 3


def test_scene_layouts_rows_and_columns(store):
    p = store.create("p")
    s = store.create_scene(p.id, ["a", "b", "c"])
    assert (s.rows, s.cols, s.views) == (1, 3, 3)
    s.rows, s.cols, s.views = 3, 1, 3                     # three stacked
    store.save_scene(p.id, s)
    back = store.get_scene(p.id, s.id)
    assert (back.rows, back.cols, back.views) == (3, 1, 3) and back.clip_ids() == ["a", "b", "c"]


def test_scenes_saved_before_layouts_get_the_default_layout(store):
    folder = store.root / "older"
    folder.mkdir()
    (folder / "project.json").write_text(json.dumps({
        "id": "older", "name": "Older", "version": 2,
        "scenes": [{"id": "s", "name": "S", "views": 4, "slots": []},
                   {"id": "t", "name": "T", "views": 2, "rows": 3, "cols": 3, "slots": []}]}))
    s, t = store.get("older").scenes
    assert (s.rows, s.cols, s.views) == (2, 2, 4)
    assert (t.rows, t.cols, t.views) == (1, 2, 2)          # 3×3 is too many: default for 2
