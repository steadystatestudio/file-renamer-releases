"""Stable application identity and storage, independent of executable names and versions."""

from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths

ORGANIZATION_NAME = "Steady State Studio"
APPLICATION_NAME = "File Renamer"


def configure_application(app, version: str) -> None:
    app.setOrganizationName(ORGANIZATION_NAME)
    app.setApplicationName(APPLICATION_NAME)
    app.setApplicationVersion(version)


def application_data_dir() -> Path:
    return Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation))


def application_settings() -> QSettings:
    return QSettings(QSettings.IniFormat, QSettings.UserScope, ORGANIZATION_NAME, APPLICATION_NAME)
