"""Child style/font invalidation must refresh the fixed action-row geometry."""
import time

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from file_renamer.gui import MainWindow


def wait_for(app, predicate, seconds=2):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert predicate()


def test_child_style_change_refreshes_action_row_without_window_resize(app, tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    window = MainWindow(tmp_path / "data", settings)
    window.show()
    try:
        for _ in range(6):
            app.processEvents()
        original_height = window.action_row.height()
        # Stylesheets propagate child FontChange/LayoutRequest after the parent
        # style event. The parent width and font do not change in this case.
        window.rename.setStyleSheet("font-size: 24pt;")
        wait_for(app, lambda: window.action_row.height() ==
                 window.action_row.height_for_width(window.action_row.width()) and
                 window.action_row.height() > original_height)
        assert window.rename.height() == window.rename.sizeHint().height()
        heights = []
        for width in (1280, 960, 820, 1):
            window.resize(width, window.height())
            wait_for(app, lambda: window.action_row.height() ==
                     window.action_row.height_for_width(window.action_row.width()))
            heights.append(window.action_row.height())
            assert window.rename.x() >= window.rule_controls.geometry().right() + 8
            assert window.rename.geometry().right() + 8 <= window.undo.x()
        assert len(set(heights)) == 1
    finally:
        window.close()
        QApplication.processEvents()
