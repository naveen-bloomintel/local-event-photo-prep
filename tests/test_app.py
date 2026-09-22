from pathlib import Path

from PIL import Image
from streamlit.testing.v1 import AppTest

from event_photo_prep.pipeline import analyze_event


def _analyzed_event(root: Path) -> Path:
    photo = root / "Fuji" / "sample.jpg"
    photo.parent.mkdir(parents=True)
    Image.new("RGB", (640, 480), (90, 110, 140)).save(photo)
    analyze_event(root)
    return root


def test_all_streamlit_workspaces_render_without_runtime_errors(tmp_path: Path) -> None:
    event = _analyzed_event(tmp_path / "event")
    app = AppTest.from_file("../streamlit_app.py", default_timeout=20)
    app.session_state["event"] = str(event)
    app.run()
    assert not app.exception

    for view in ["Burst review", "Before / after", "Finish", "Review grid"]:
        app.get_by_key("workspace_view").set_value(view)
        app.run()
        assert not app.exception


def test_before_after_uses_type_consistent_sliders(tmp_path: Path) -> None:
    event = _analyzed_event(tmp_path / "event")
    app = AppTest.from_file("../streamlit_app.py", default_timeout=20)
    app.session_state["event"] = str(event)
    app.session_state["workspace_view"] = "Before / after"
    app.run()
    assert not app.exception
    assert app.slider
    exposure = app.get_by_key(f"edit-{event / 'Fuji' / 'sample.jpg'}-Exposure2012")
    assert isinstance(exposure.value, float)
