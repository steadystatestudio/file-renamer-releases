import sys

import pytest

from file_renamer.application_paths import application_data_dir, application_settings, configure_application


@pytest.mark.parametrize("updated_version", ["2.0.2", "3.0.0"])
def test_updates_and_executable_names_keep_storage_paths(app, monkeypatch, updated_version):
    identity = (app.organizationName(), app.applicationName(), app.applicationVersion())
    try:
        monkeypatch.setattr(sys, "argv", ["File-Renamer-2.0.1-x86_64.AppImage"])
        configure_application(app, "2.0.1")
        data_dir = application_data_dir()
        settings_path = application_settings().fileName()

        monkeypatch.setattr(sys, "argv", ["File-Renamer-x86_64.AppImage"])
        configure_application(app, updated_version)
        assert application_data_dir() == data_dir
        assert application_settings().fileName() == settings_path
        assert app.applicationName() == "File Renamer"
        assert app.applicationVersion() == updated_version
        assert "2.0.1" not in str(data_dir)
        assert updated_version not in str(data_dir)
        assert updated_version not in settings_path
    finally:
        app.setOrganizationName(identity[0])
        app.setApplicationName(identity[1])
        app.setApplicationVersion(identity[2])
