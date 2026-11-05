"""Regression checks for useful minimum windows and monitor changes."""

import pytest
from PySide6.QtCore import QCoreApplication, QDeadlineTimer, QEvent, QPoint, QRect, QSettings
from PySide6.QtGui import QFont, QPalette, QScreen
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolTip

from file_renamer import appearance
from file_renamer.appearance import configure_appearance
from file_renamer.desktop_geometry import WorkAreaProvider
from file_renamer.gui import MainWindow
from file_renamer.themes import apply_theme


def copied_appearance_value(value):
    if isinstance(value, QFont):
        return QFont(value)
    if isinstance(value, dict):
        return {key: copied_appearance_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [copied_appearance_value(item) for item in value]
    return value


def wait_for_font_and_layout(app, window, points):
    """Measure only after the actual controls and their queued layout agree."""
    # A complete suite retains other windows whose synchronous Qt style polish
    # can occupy the first event drain for 60--95s. This is a test-only ceiling;
    # require three settled observations rather than accepting a transient size.
    deadline = QDeadlineTimer(120_000)
    stable = 0
    while not deadline.hasExpired():
        QTest.qWait(20)
        controls = (window, window.add_files, window.rename, window.undo,
                    *window.rule_buttons, window.table, window.progress)
        font_ready = app.font().pointSizeF() == points and all(
            control.fontInfo().pointSizeF() == points for control in controls)
        timers = (window.layout_timer, window.action_row.metrics_timer, window.window_size_guard.timer)
        if font_ready and not any(timer.isActive() for timer in timers):
            stable += 1
            if stable == 3:
                return
        else:
            stable = 0
    assert app.font().pointSizeF() == points
    assert all(control.fontInfo().pointSizeF() == points for control in controls), [
        (type(control).__name__, control.fontInfo().pointSizeF()) for control in controls]
    raise AssertionError("Owned window font/layout did not settle")


@pytest.fixture
def sized_window(app, tmp_path, monkeypatch):
    previous_font, previous_palette = QFont(app.font()), QPalette(app.palette())
    previous_style, previous_tooltip = app.styleSheet(), QFont(QToolTip.font())
    names = ("_studio_pilot_settings", "_studio_appearance_theme_key", "_studio_refresh_appearance",
             "_studio_appearance_resolved_font", "_studio_appearance_values", "_studio_appearance_resolution",
             "_studio_host_appearance", "_studio_pilot_providers", "_studio_pilot_configured",
             "_studio_system_font_initialized")
    absent = object()
    previous = {name: copied_appearance_value(getattr(app, name, absent)) for name in names}
    properties = {name: app.property(name) for name in
                  ("dark", "studioAppearanceDiagnostics", "studioWorkAreaDiagnostics")}
    watcher = getattr(app, "_studio_appearance_watcher", None)
    previous_signature = watcher.font_signature if watcher else None
    previous_timers = [(timer, timer.remainingTime()) for timer in
                       (watcher.refresh_timer, watcher.host_timer)] if watcher else []
    for timer, _ in previous_timers:
        timer.stop()
    area = [QRect(0, 0, 3440, 1392)]
    monkeypatch.setattr(QScreen, "availableGeometry", lambda _: QRect(area[0]))
    # These are text/layout tests, not native-provider tests. A controller owned
    # by this fixture cannot be overwritten by older windows' queued queries.
    provider = WorkAreaProvider(app)
    provider.enabled = False
    provider.reason = "native-qt-platform"
    provider.refresh_timer.stop()
    monkeypatch.setattr(app, "_studio_workarea_provider", provider, raising=False)
    for function, name in (("_start_native", "gtk"), ("_start_portal", "portal")):
        monkeypatch.setattr(appearance, function,
                            lambda instance, generation, provider_name=name: appearance._provider_finished(
                                instance, generation, provider_name, {"reason": "fixture-unavailable"}))
    settings = QSettings(str(tmp_path / "window.ini"), QSettings.IniFormat)
    settings.setValue("appearance/font_mode", "custom")
    settings.setValue("appearance/font_family", QFont("Segoe UI", 9).family())
    settings.setValue("appearance/font_size_pt", 9)
    # Invalidate outstanding appearance probes before installing the test's
    # explicit override; their late replies must not become this test's state.
    window = None
    try:
        configure_appearance(app, settings, refresh=True, theme_key="theme")
        window = MainWindow(tmp_path, settings)
        window.show()
        wait_for_font_and_layout(app, window, 9)
        yield window, area
    finally:
        if window is not None:
            window.close()
            window.deleteLater()
        provider.close()
        provider.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()
        app._studio_refresh_appearance = None
        app.setFont(previous_font)
        app.setPalette(previous_palette)
        app.setStyleSheet(previous_style)
        QToolTip.setFont(previous_tooltip)
        for name, value in previous.items():
            if value is absent:
                if hasattr(app, name):
                    delattr(app, name)
            else:
                setattr(app, name, value)
        for name, value in properties.items():
            app.setProperty(name, value)
        watcher = getattr(app, "_studio_appearance_watcher", None)
        if watcher:
            watcher.refresh_timer.stop()
            watcher.host_timer.stop()
            watcher.font_signature = previous_signature or app.font().toString()
        for timer, remaining in previous_timers:
            if remaining >= 0:
                timer.start(remaining)


def test_dragging_smaller_keeps_complete_workspace(sized_window):
    window, _ = sized_window
    window.resize(1, 1)
    QTest.qWait(80)
    assert window.width() >= window.content_root.minimumWidth()
    assert window.width() < 900
    assert window.height() >= 650
    scroll = getattr(window, "work_scroll", None)
    if scroll is not None:
        assert scroll.horizontalScrollBar().maximum() == 0
        assert scroll.verticalScrollBar().maximum() == 0
    assert window.size() == window.minimumSize()


def test_smaller_monitor_caps_minimum_then_restores_it(sized_window):
    window, area = sized_window
    normal = window.minimumSize()
    original_font = window.font()
    area[0] = QRect(0, 0, 800, 600)
    window.window_size_guard.update()
    QTest.qWait(80)
    assert window.frameGeometry().width() <= 800
    assert window.frameGeometry().height() <= 600
    assert window.font() == original_font
    area[0] = QRect(0, 0, 3440, 1392)
    window.window_size_guard.update()
    QTest.qWait(80)
    assert window.minimumWidth() >= normal.width()
    assert window.minimumHeight() >= normal.height()


def test_larger_font_measures_controls_and_preserves_useful_workspace(sized_window):
    window, _ = sized_window
    before = window.minimumSize()
    window.settings.setValue("appearance/font_size_pt", 18)
    configure_appearance(QApplication.instance(), window.settings)
    apply_theme(QApplication.instance())
    wait_for_font_and_layout(QApplication.instance(), window, 18)
    assert window.font().pointSize() == 18
    assert window.rename.fontInfo().pointSizeF() == 18
    assert window.rule_buttons[0].fontInfo().pointSizeF() == 18
    assert window.minimumWidth() > before.width()
    assert window.minimumHeight() == max(650, window.centralWidget().layout().minimumSize().height())
    window.resize(window.minimumSize())
    QTest.qWait(80)
    assert window.rule_controls.geometry().right() + 8 <= window.rename.x()
    assert window.rename.geometry().right() + 8 <= window.undo.x()
    assert window.table.viewport().height() >= 3 * window.table.fontMetrics().height()
    status_bottom = window.progress.mapTo(window, QPoint(0, 0)).y() + window.progress.height()
    assert status_bottom <= window.height()


def test_font14_accepts_smaller_compositor_client_height(sized_window):
    window, area = sized_window
    # A compositor can reserve panel/decorations outside Qt's reported work area.
    # A logical workspace floor must permit its smaller client configuration.
    area[0] = QRect(0, 0, 1280, 800)
    window.settings.setValue("appearance/font_size_pt", 14)
    configure_appearance(QApplication.instance(), window.settings)
    apply_theme(QApplication.instance())
    QTest.qWait(150)
    window.window_size_guard.update()
    window.resize(960, 720)
    QTest.qWait(150)
    assert window.font().pointSize() == 14
    assert window.height() == 720
    assert window.minimumHeight() <= 720
    assert window.table.viewport().height() >= 3 * window.table.fontMetrics().height()
    status_bottom = window.progress.mapTo(window, QPoint(0, 0)).y() + window.progress.height()
    assert status_bottom <= 720
