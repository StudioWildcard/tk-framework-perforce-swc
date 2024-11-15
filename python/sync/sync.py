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
Common Perforce sync utility methods
"""


import os
import socket
import re
import threading
import traceback


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
    Encapsulate loading sync window. Entity data is handed directly to the UI so that
    it can delegate data lookups from p4 in workers rather than stall main thread while
    user waits for visual feedback of the UI init completing.
    """

    def __init__(self, fw):
        """
        Construction
        """
        self._fw = fw
        self._p4 = None
        self.p4_server = self._get_p4_server()


    def sync_with_dlg(self, app, entities_to_sync,  specific_files=False):
        """
        Show the sync window for user file syncing

        :returns: None
        """
        # store the entities to sync
        self.entities_to_sync = entities_to_sync
        self.app = app
        self.specific_files = specific_files

        try:
            # ensure this always runs on the main thread:
            return self._fw.engine.execute_in_main_thread(self._sync_with_dlg)
        finally:
            pass
        
    def _sync_with_dlg(self):
        """
        Actual implementation of sync_with_dlg.

        :returns: None
        """
        server = self.p4_server
        sg_user = sgtk.util.get_current_user(self._fw.sgtk)
        user = self._fw.execute_hook("hook_get_perforce_user", sg_user=sg_user)

        try:
            from ..widgets import SyncForm

            result, _ = self._fw.engine.show_modal("Perforce Sync ", self._fw, SyncForm, 
                                                   self.app, self.entities_to_sync, self.specific_files)

            if result == QtGui.QDialog.Accepted:
                pass

        except Exception as e:
            self._fw.log_error(e)

        return None


    def _get_p4_server(self):
        user = sgtk.util.get_current_user(self._fw.sgtk)        
        sg_user = self._fw.shotgun.find_one('HumanUser', [['id', 'is', user['id']]], ["sg_region"])
        server_field = self._fw.get_setting("server_field")
        sg_project = self._fw.shotgun.find_one('Project', [['id', 'is', self._fw.context.project['id']]], [server_field])
        server = sg_project.get(server_field)
        region = sg_user.get("sg_region")
        sg_server = self._fw.shotgun.find_one('CustomNonProjectEntity02', [['id', 'is', server['id']]], [region])

        if not sg_server:
            self._fw.log_error("No server was configured for this project! Enter the p4 server in the project field '{}'".format(server_field))
            return None

        return str(sg_server.get(region))


def sync_with_dialog(app, entities_to_sync, specific_files=False):
    """
    Show the Perforce sync dialog

    :returns Qt UI:    A new Perforce sync dialog
    """
    fw = sgtk.platform.current_bundle()
    try:
        return SyncHandler(fw).sync_with_dlg(app, entities_to_sync, specific_files=specific_files)
    except Exception  as e:
        fw.log_error(traceback.format_exc())
