# Copyright (c) 2013 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

"""
Common Perforce connection utility methods
"""

import os
import socket
import re
import threading

import sgtk
from sgtk import TankError
from sgtk.platform.qt import QtGui

from P4 import P4, P4Exception


class SgtkP4Error(TankError):
    """
    Specialisation of TankError raised after catching and processing a P4Exception
    """


class SyncHandler(object):
    """
    Encapsulate connecting to Perforce.  This pulls the settings from the various
    different locations (config, Shotgun, user prefs) as well as being responsible
    for prompting the user if needed (and UI is available)
    """

    def __init__(self, fw):
        """
        Construction
        """
        self._fw = fw
        self._p4 = None
        self.p4_server = self._get_p4_server()


    def sync_with_dlg(self, app, entities_to_sync):
        """
        Present the connection dialog to the user and prompt them to connect in a thread-safe
        manner.

        :returns: A connected, logged-in p4 instance if successful.
        """

        self.entities_to_sync = entities_to_sync
        self.app = app

        try:
            # ensure this always runs on the main thread:
            return self._fw.engine.execute_in_main_thread(self._sync_with_dlg)
        finally:
            pass
        
    def _sync_with_dlg(self):
        """
        Actual implementation of connect_with_dlg.

        :returns: A connected, logged-in p4 instance if successful.
        """
        server = self.p4_server
        sg_user = sgtk.util.get_current_user(self._fw.sgtk)
        user = self._fw.execute_hook("hook_get_perforce_user", sg_user=sg_user)

        try:
            from ..widgets import SyncForm

            result, _ = self._fw.engine.show_modal("Perforce Sync ", self._fw, SyncForm, 
                                                   self.app, self.entities_to_sync)

            if result == QtGui.QDialog.Accepted:
                pass

        except Exception as e:
            self._fw.log_error(e)

        return None


    def _get_p4_server(self):
        server_field = self._fw.get_setting("server_field")
        sg_project = self._fw.shotgun.find_one('Project', [['id', 'is', self._fw.context.project['id']]], [server_field])
        server = sg_project.get(server_field)

        if not server:
            self._fw.log_error("No server was configured for this project! Enter the p4 server in the project field '{}'".format(server_field))
            return None

        return str(sg_project.get(server_field))


def sync_with_dialog(app, entities_to_sync):
    """
    Show the Perforce sync dialog

    :returns Qt UI:    A new Perforce sync dialog
    """

    fw = sgtk.platform.current_bundle()
    return SyncHandler(fw).sync_with_dlg(app, entities_to_sync)
