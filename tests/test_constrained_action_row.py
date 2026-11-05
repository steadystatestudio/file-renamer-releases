"""A height-constrained compositor floor must preserve measured Rename geometry."""
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QRect, QSettings, Signal

from file_renamer import appearance, gui, system_fonts, window_size


def settle(app, predicate):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(.005)
    assert predicate()


@pytest.mark.parametrize("points", [9, 18])
def test_short_validated_area_retains_collision_row_and_restores_full_workspace(app, tmp_path, monkeypatch, points):
    """Unit-test declared constraints and real layout; VM checks cover native placement."""
    old_font, old_style = app.font(), app.styleSheet()
    old_settings = getattr(app, "_studio_pilot_settings", None)
    old_theme_key = getattr(app, "_studio_appearance_theme_key", "theme")
    monkeypatch.setattr(app, "_studio_refresh_appearance", None, raising=False)
    monkeypatch.setattr(system_fonts.QStandardPaths, "writableLocation", lambda *_: str(tmp_path / "diagnostics"))
    for name, function in (("gtk", "_start_native"), ("portal", "_start_portal")):
        monkeypatch.setattr(appearance, function,
                            lambda instance, generation, provider=name: appearance._provider_finished(
                                instance, generation, provider, {"reason": "fixture-unavailable"}))
    area = [QRect(0, 0, 2048, 480)]

    class FixedWorkArea(QObject):
        changed = Signal()
        enabled = True
        last_details = {"source": "x11-ewmh"}

        def refresh(self):
            pass

    provider = FixedWorkArea()
    monkeypatch.setattr(window_size, "workarea_provider", lambda _: provider)
    monkeypatch.setattr(gui, "workarea_provider", lambda _: provider)
    monkeypatch.setattr(window_size, "available_geometry", lambda *_: area[0])
    monkeypatch.setattr(gui, "desktop_available_geometry", lambda *_: area[0])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setValue("appearance/font_mode", "custom")
    settings.setValue("appearance/font_family", old_font.family())
    settings.setValue("appearance/font_size_pt", points)
    window = gui.MainWindow(tmp_path / "data", settings)
    maximized = [False]
    requests = []

    # Offscreen has no compositor matching the synthetic work area. Emulate its
    # state/configure response while leaving the actual Qt widget layout live.
    def compositor_maximize():
        requests.append(True)
        maximized[0] = True
        frame = window.frameGeometry()
        extra_h = max(0, frame.height() - window.height())
        window.resize(1800, area[0].height() - extra_h)

    monkeypatch.setattr(window, "isMaximized", lambda: maximized[0])
    monkeypatch.setattr(window, "showMaximized", compositor_maximize)
    guard = window.window_size_guard
    try:
        # Do not advertise the capped full 650px workspace as a hard pre-map
        # minimum. The compositor needs room to place this 480px-tall client.
        guard.update()
        assert guard.constrained_native_maximum
        assert guard.preferredMinimum.height() >= 650
        assert window.minimumHeight() < area[0].height()
        window.show()
        settle(app, lambda: requests and not guard.timer.isActive() and not window.layout_timer.isActive())
        assert window.font().pointSizeF() == points
        assert max(row for row, _ in window._rule_placements) == 0
        margins = window.content_root.layout().contentsMargins()
        collision = window.action_row.minimumSizeHint().width() + margins.left() + margins.right()
        row_height = window.action_row.height()
        assert window.minimumWidth() >= collision
        for width in (1800, collision + 160, collision, 1):
            window.resize(width, window.height())
            settle(app, lambda: not guard.timer.isActive() and not window.layout_timer.isActive())
            row = window.action_row
            row.arrange()
            button_width = row.action_width()
            expected_x = max(row.controls.sizeHint().width() + 8,
                             min((row.width() - button_width) // 2, row.width() - 2 * button_width - 8))
            assert window.width() >= window.minimumWidth() >= collision
            assert row.height() == row_height
            assert window.rename.x() == expected_x
            assert window.rename.x() >= row.controls.geometry().right() + 8
            assert window.rename.geometry().right() + 8 <= window.undo.x()
            assert window.rect().contains(window.progress.mapTo(window, window.progress.rect().bottomRight()))
            assert window.table.viewport().height() >= 2 * window.table.fontMetrics().height()
            assert window.font().pointSizeF() == points

        area[0] = QRect(0, 0, 2048, 1200)
        provider.changed.emit()
        settle(app, lambda: not guard.constrained_native_maximum and window.minimumHeight() >= 650
               and not guard.timer.isActive() and not window.layout_timer.isActive())
        assert maximized[0], "More room releases the constraint without overriding the user's maximized state"
        assert window.minimumWidth() >= collision
        assert window.font().pointSizeF() == points
        assert window.table.viewport().height() >= 2 * window.table.fontMetrics().height()
    finally:
        guard.timer.stop()
        guard._geometry_diagnostics_timer.stop()
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        appearance.configure_appearance(app, old_settings, refresh=True, theme_key=old_theme_key)
        app.setStyleSheet(old_style)
        app.setFont(old_font)
        app.processEvents()
