# Copyright (c) 2013 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

import sgtk
from sgtk.platform.qt import QtCore, QtGui

logger = sgtk.platform.get_logger(__name__)


def sync_path_with_dialog(p4, sync_path, title="Perforce Sync", message=None):
    """
    Sync a Perforce path while showing a modal progress dialog.
    Blocks until sync completes. Returns the list of synced items.

    :param p4: Connected P4 instance
    :param sync_path: Local or depot path to sync (e.g. ``B:/Depot/Tools/...``)
    :param title: Dialog window title
    :param message: Dialog message (defaults to ``Syncing <path>...``)
    :returns: List of sync results, or empty list on failure
    """
    if not message:
        message = "Syncing {}...".format(sync_path)

    # Show an indeterminate progress dialog so the user knows something is happening.
    # The dialog won't animate during the blocking P4 call, but it provides visual
    # feedback that a sync is in progress.
    progress = QtGui.QProgressDialog(message, None, 0, 0)
    progress.setWindowTitle(title)
    progress.setWindowModality(QtCore.Qt.ApplicationModal)
    progress.setCancelButton(None)
    progress.setMinimumDuration(0)
    progress.show()
    QtCore.QCoreApplication.processEvents()

    result = []
    try:
        result = p4.run("sync", sync_path) or []
    except Exception as e:
        logger.warning("Sync failed for %s: %s", sync_path, e)
    finally:
        progress.close()

    return result
