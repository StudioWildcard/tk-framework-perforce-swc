import sgtk
from sgtk.platform.qt import QtCore, QtGui
import os
import traceback
import pprint
import random
import time

from ..sync.resolver import TemplateResolver


class SyncSignaller(QtCore.QObject):
    """
    Create signaller class for Sync Worker, required for using signals due to QObject inheritance
    """
    started = QtCore.Signal(dict)
    finished = QtCore.Signal()
    progress = QtCore.Signal(dict) # (path to sync, p4 sync response)

class AssetInfoGatherSignaller(QtCore.QObject):
    """
    Create signaller class for AssetInfoGather Worker, required for using signals due to QObject inheritance
    """
    progress = QtCore.Signal(str)
    root_path_resolved = QtCore.Signal(str)
    info_gathered = QtCore.Signal(dict) 
    item_found_to_sync = QtCore.Signal(dict)
    status_update = QtCore.Signal(str)
    include_step = QtCore.Signal(str)

class SyncWorker(QtCore.QRunnable):

    # structurally anticipate basic p4 calls, which will route to the main form. 
    p4 = None 
    fw = None
    path_to_sync = None
    asset_name = None

    def __init__(self):
        """
        Handles syncing specific file from perforce depot to local workspace on disk
        """
        super(SyncWorker, self).__init__()
        self.signaller = SyncSignaller()

        # use signals from Signaller, since we cant in a non-QObject derrived
        # object like this QRunner. 
        self.started = self.signaller.started
        self.finished = self.signaller.finished
        self.progress = self.signaller.progress

    @QtCore.Slot()
    def run(self):
        
        """
        Ryn syncs from perforce, signals information back to main thread. 
        """
        self.p4 = self.fw.connection.connect()

        # self.fw.log_debug("starting thread in pool to sync {}".format(self.path_to_sync))
        self.started.emit({
            "asset_name" : self.asset_name,
            "sync_path" : self.path_to_sync
            }
        )

        # run the syncs
        p4_response = self.p4.run("sync", ["-f"], "{}#head".format(self.path_to_sync))
        self.fw.log_debug(p4_response)

        # emit item key and p4 response to main thread
        self.progress.emit({
            "asset_name" : self.asset_name,
            "sync_path" : self.path_to_sync, 
            "response" : p4_response
            }
        )


class AssetInfoGatherWorker(QtCore.QRunnable):

    def __init__(self, app=None, entity=None, framework=None):
        """
        Handles gathering information about specific asset from SG and gets related Perforce information
        """
        super(AssetInfoGatherWorker, self).__init__()

        self.app = app
        self.entity = entity


        self._items_to_sync = []
        self._status = None
        self._icon = None
        self._detail = None

        self.fw = framework
        self.asset_item = None

        self.signaller = AssetInfoGatherSignaller()

        self.info_gathered = self.signaller.info_gathered
        self.progress = self.signaller.progress
        self.root_path_resolved = self.signaller.root_path_resolved
        self.item_found_to_sync = self.signaller.item_found_to_sync
        self.status_update = self.signaller.status_update
        self.include_step = self.signaller.include_step

    @property
    def asset_name(self):
        return self.asset_item.get('context').entity.get('name')
        
    @property
    def root_path(self):
        return self.asset_item.get('root_path')
    
    @property
    def status(self):
        if self.asset_item.get('error'):
            self._icon = "warning"
            self._status = "Error"
            self._detail = self.asset_item.get('error')
        return self._status


    def collect_and_map_info(self):
        """
        Call perforce for response and form data we will signal back
        """
        if self.status != 'error':
            self.get_perforce_sync_dry_reponse()

        # payload that we'll send back to the main thread to make UI item with
        self.info_to_signal = {
            "asset_name": self.asset_name,   
            "status" : self._status,
            "details" : self._detail,
            "icon" : self._icon,
            "asset_item" : self.asset_item,
            "items_to_sync": self._items_to_sync
        }


    def get_perforce_sync_dry_reponse(self):
        """
        Get a response from perforce about our wish to sync a specific asset root path,
        Contextually use response to drive our status that we show the user. 1
        """
        if self.root_path:
            self.p4 = self.fw.connection.connect()

            sync_response = self.p4.run("sync", ["-n"], "{}#head".format(self.root_path))
            self.fw.log_debug("P4 log:" + str(sync_response))


            if not sync_response:
                self._status = "Not In Depot"
                self._icon = "error"
                self._detail = "Nothing in depot resolves [{}]".format(self.root_path)

            elif len(sync_response) is 1 and type(sync_response[0]) is str:
                self._status = "Syncd"
                self._icon = "success"
                self._detail = "Nothing new to sync for [{}]".format(self.root_path)
            else:
                # if the response from p4 has items... make UI elements for them
                self._items_to_sync = [i for i in sync_response if type(i) != str]
                self._status = "{} items to Sync".format(len(self._items_to_sync))
                self._icon = "load"
                self._detail = self.root_path


    @QtCore.Slot()
    def run(self):

        """
        Checks if there are errors in the item, signals that, or if not, gets info regarding what there is to sync. 
        """
        
        self.template_resolver = TemplateResolver(app=self.app,
                                            entity=self.entity )

        self.asset_item = self.template_resolver.entity_info
        progress_status_string = ""

        self.status_update.emit("Requesting sync information for {}".format(self.asset_name))

        #self.fw.log_info(self.asset_item)
        self.collect_and_map_info()
        
        self.info_gathered.emit(self.info_to_signal)
        if self.status == 'Syncd':
            progress_status_string = " (Nothing to sync. Skipping...)"

        if self.status != "Error":
            
            for item in self._items_to_sync:
                step = None
                # get steps
                try:
                    for t in ['env_asset_work_area', "asset_child_work_area", "asset_work_area", "anim_asset_work_area"]:
                        template = self.app.sgtk.templates[t]
                        fields = template.get_fields(item.get('clientFile'))
                        if "Step" in fields.keys():
                            step = fields.get('Step')
                            self.include_step.emit( fields.get('Step') )

                except Exception as e:
                    template = str(e)
                self.fw.log_info("TEMPLATE!!!! {}".format(str(template)))
                self.item_found_to_sync.emit( {
                    "asset_name" : self.asset_name,
                    "item_found" : item,
                    "step" : step
                    } 
                )
        else:
            progress_status_string = " (Encountered error. See details)"

        self.progress.emit("Gathering info for {} {}".format(self.asset_name, progress_status_string))
