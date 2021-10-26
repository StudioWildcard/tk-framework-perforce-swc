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
Common utilities for reconciling the state of Perforce files
"""

import os
import re

from P4 import P4Exception, Map as P4Map  # Prefix P4 for consistency

import sgtk
from sgtk import TankError
from tank_vendor import six
from tank_vendor.six.moves import urllib

logger = sgtk.LogManager.get_logger(__name__)


class P4Reconciler:
    _root_path = None
    _p4 = None
    actions = {}

    def __init__(self, p4, root_path):
        """
        Object to handle scanning directories for statuses, then keeping it cached
        to individually reconcile the discovered paths as needed.

        :param p4: perforce connection
        :param root_path: base path to scan from
        """
        self.p4 = p4
        self.root_path = root_path


    def __getattr__(self, item):
        """
        Intercept action info retrievals and return them on the fly
        """
        avail_actions = list(self.actions.keys())
        avail_action_info_list = ["{}_info".format(i) for i in avail_actions]
        avail_action_file_list = ["{}_files".format(i) for i in avail_actions]
        actions =  self.__dict__.get('actions')
        if item in avail_action_info_list:
            return actions.get(item.split('_')[0])
        elif item in avail_action_file_list:
            return [i.get('clientFile') for i in actions.get(item.split('_')[0])]
        else:
            raise AttributeError("Attribute '{}' not does not exist. If you are attempting"\
            "to get reconcile states, please use any of {} for details of each, or {} for a list of"\
            " paths for each.".format(item, avail_action_info_list, avail_action_file_list))

    @property
    def root(self):
        return self.p4.fetch_client()._root

    @property
    def p4(self):
        return self._p4

    @p4.setter
    def p4(self, value):
        self._p4 = value

    @property
    def root_path(self):
        return self._root_path

    @root_path.setter
    def root_path(self, value):
        self._root_path = value

    def reset_collection(self):
        self.actions = {
            "add" :   [],
            "edit":   [],
            "delete": [],
            "move" :  [],
            "open" :  []
        }

    @property
    def opened_files(self):
        opened = self.p4.run('opened', os.path.join(self.root_path, "...")) 
        reformatted = []
        for open_item in opened:
            if open_item.get('client') == self.p4.client:
                client_file = open_item.get('clientFile')
                formatted_client_file = self.root + client_file.replace("//{}/".format(self.p4.client), "").replace("/", "\\")
                open_item['clientFile'] = formatted_client_file
                reformatted.append(open_item)

        return reformatted


    def recursive_scan(self, path=None):
        """
        Scan the chosen directory recursively, reconcile status of
        local file state against Perforce server. 
        Added files: File locally that doesnt exist in the depot. 
        Edited files: Files locally that have different contents than the depot files
        Deleted files: Files the arent local but expected to be by the latest depot workspace expectation.
        """
        self.reset_collection()

        if path:
            self.root_path = path
        logger.debug("Starting the reconcile scan....")   

        # get opened files
        self.actions['open'].extend(self.opened_files)
 
        for root, dirs, files in os.walk(self.root_path):

            # run for reconcile-specific calls
            response = self.p4.run('reconcile', "-m", "-n", os.path.join(root, "*"))
            if response:
                for item in response:
                    if type(item)==dict:
                        action = item.get('action') 
                        if action:
                            self.actions.get(action.split("/")[0]).append(item)


def recursive_reconcile(path):
    fw = sgtk.platform.current_bundle()
    p4 = fw.connection.connect()

    reconciler = P4Reconciler(p4, path)
    reconciler.recursive_scan()
    return reconciler