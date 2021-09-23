# Copyright (c) 2013 Studio WILDCARD.
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
import os
import traceback
import pprint
import random
import time

from sync_workers import SyncWorker, AssetInfoGatherWorker

# file base for accessing Qt resources outside of resource scope
basepath = os.path.dirname(os.path.abspath(__file__))


class SyncForm(QtGui.QWidget):

    _fw = None
    _p4 = None
        
    progress = 0
    
    def __init__(self, parent_sgtk_app, entities_to_sync, parent=None):
        """
        Construction of sync UI
        """
        QtGui.QWidget.__init__(self, parent)

        self.app = parent_sgtk_app
        self.entities_to_sync = entities_to_sync

        self._asset_item_info = {}
        self._asset_items = {}
        self._sync_items = {}

        self.threadpool = QtCore.QThreadPool.globalInstance()

        # creat UI elements and arrange them
        self.make_widgets()
        self.setup_ui()

        # add assets and what we want to sync into the view
        self.populate_assets()

    @property
    def fw(self):
        """
        Implement framework if doesnt currently exist,  return it if it does
        """
        if not self._fw:
            self._fw = sgtk.platform.current_bundle()
        return self._fw 

    @property
    def p4(self):
        """
        initializes p4 as connection setup if it doesnt exist. Passes existing if it does. 
        """
        if not self._p4:
            self._p4 = self.fw.connection.connect()
        return self._p4

    def make_widgets(self):
        """
        Makes UI widgets for the main form
        """

        # bring in global SG search widget when there arent Assets given already to the app
        # search_widget = sgtk.platform.import_framework("tk-framework-qtwidgets", "global_search_widget")
        # self.search_line_edit = search_widget.GlobalSearchWidget(self)    

        self._do = QtGui.QPushButton("Sync")
        self._asset_tree = QtGui.QTreeWidget()
        self._progress_bar = QtGui.QProgressBar()
        self._list = QtGui.QListWidget()
        self._line_edit = QtGui.QLineEdit()
        self._line_edit.setText(" ")

    def setup_ui(self):
        """
        Lays out and customizes widgets for the main form
        """       

        # set main layout
        self._main_layout = QtGui.QVBoxLayout()
        self.setLayout(self._main_layout)

        # hide progress until we run the sync
        self._progress_bar.setVisible(False)

        # asset tree setup
        self.tree_header = ["Asset Name", "Status", "Detail"]
        for h in self.tree_header:
            setattr(self, h.replace(' ', "_").upper(), self.tree_header.index(h))

        self._asset_tree.setAnimated(True)
        self._asset_tree_header = QtGui.QTreeWidgetItem(self.tree_header)
        self._asset_tree.setHeaderItem(self._asset_tree_header)  
        self._asset_tree.setWordWrap(True)
        self._asset_tree.setColumnWidth(0, 150)
        
        # arrange widgets in layout
        self._main_layout.addWidget( self._asset_tree)
        self._main_layout.addWidget(self._progress_bar)
        self._main_layout.addWidget(self._do)

        # css
        self.setStyleSheet("""QTreeWidget::item { padding: 5px; }""" )
        
        # signal connections
        self._do.clicked.connect(self.start_sync)


    def make_top_level_tree_item(self, asset_name=None, status=None, details=None, icon=None):
        """
        Creates QTreeWidgetItem to display asset information
        """
        tree_item = QtGui.QTreeWidgetItem()

        tree_item.setText(self.ASSET_NAME, asset_name)
        tree_item.setText(self.STATUS, status)
        tree_item.setText(self.DETAIL, details)
        tree_item.setIcon(self.STATUS, self.make_icon(icon))

        self._asset_tree.addTopLevelItem(tree_item)
        return tree_item


    def make_sync_tree_item(self, sync_item_info):
        """
        Creates child QTreeWidgetItem under asset item to display filename and status of the sync
        """
        #self.fw.log_info('trying to make child item for {}'.format(sync_item_info))

        asset_name = sync_item_info.get("asset_name")
        item_found = sync_item_info.get("item_found")
        tree_item = self._asset_items[asset_name].get("tree_widget")

        child_tree_item = QtGui.QTreeWidgetItem(tree_item)

        asset_file_path = item_found.get('clientFile') 
        asset_file_name = os.path.basename(item_found.get('clientFile'))
            

        child_tree_item.setText(self.ASSET_NAME, asset_file_name) #If it is not clientFile specifically it seems like the name is within that info at least the correct wording is probably in clientFile
        child_tree_item.setText(self.STATUS, "Ready")
        child_tree_item.setText(self.DETAIL, asset_file_path) #after testing it works as intended but we need to link it to the actual names the correct wording is probably in depotFile
        child_tree_item.setIcon(self.STATUS, self.make_icon("load"))


        child_widgets = self._asset_items[asset_name].get("child_widgets")
        child_widgets[ asset_file_path ] = child_tree_item
        

    def asset_info_handler(self, info_processed_dict):
        """
        Main handler for asset information. 
        """
        tree_widget = self.make_top_level_tree_item(asset_name=info_processed_dict.get("asset_name"),
                                      status= info_processed_dict.get("status"),
                                      details= info_processed_dict.get("details"),
                                      icon = info_processed_dict.get("icon")                              
        )
        asset_UI_mapping = {}
        asset_UI_mapping['tree_widget']= tree_widget
        asset_UI_mapping['asset_info']= info_processed_dict.get("asset_item")
        asset_UI_mapping['child_widgets'] = {}

        self._asset_items[info_processed_dict.get("asset_name")] = asset_UI_mapping
        

    def set_progress_message(self, message=None):
        self._progress_bar.setVisible(True)
        self._progress_bar.setFormat("{} %p%".format(message))


    def iterate_progress(self, message=None):
        """
        Iterate global progress counter and update the progressbar widget
        Detect if progress is globally complete and handle hiding the progress widget
        """
        self._progress_bar.setVisible(True)
        self.progress += 1
        self.fw.log_info(self.progress)
        self._progress_bar.setValue(self.progress)
        self.set_progress_message(message)
        if self._progress_bar.value() == self._progress_bar.maximum():
            self.set_progress_message("{} complete".format(message))
            self._progress_bar.setVisible(False)

    def populate_assets(self):
        """
        Iterate through tk-multi-perforce delivered list of asset information, 
        Utilize a global threadpool to process workers to ask P4 server for what 
        there is to sync for these. 
        """
        self.asset_item_registry = {}  

        self.sync_items = {}
        self.sync_order = []
        self.progress = 0

        self.progress_maximum = len(self.entities_to_sync)
        self._progress_bar.setRange(0, self.progress_maximum)
        self._progress_bar.setValue(0)
        self.set_progress_message("Requesting asset information for SG selection...")

        self.fw.log_info(len(self.entities_to_sync))
        # iterate all parent assets
        for entity_to_sync in self.entities_to_sync:

            asset_info_gather_worker = AssetInfoGatherWorker(app=self.app,
                                                             entity=entity_to_sync,
                                                             framework=self.fw)

            asset_info_gather_worker.info_gathered.connect( self.asset_info_handler )
            asset_info_gather_worker.progress.connect( self.iterate_progress )
            asset_info_gather_worker.item_found_to_sync.connect(self.make_sync_tree_item)
            asset_info_gather_worker.status_update.connect(self.set_progress_message)

            self.threadpool.start(asset_info_gather_worker)


    def make_icon(self, name):
        """
        Helper to return QIcon from our limited icon schema used. 
        """
        return QtGui.QIcon(os.path.join(basepath, 'resources', "status_{}.png".format(name)))


    def sync_in_progress(self, sync_item):
        """
        Handle signal from SyncWorker.started to inform user that sync has started within sync_item_widget. 
        This sync_item_widget is looked up from our global asset dictionary using the signal payload arg [dict]
        """

        asset_name = sync_item.get('asset_name')
        sync_path = sync_item.get("sync_path")

        sync_item_widget = self._asset_items[asset_name].get('child_widgets').get(sync_path)
        asset_item_widget = self._asset_items[asset_name].get('tree_widget')

        icon  = self.make_icon("syncing")
        sync_item_widget.setIcon(1, icon)
        sync_item_widget.setText(1, "Syncing")

        self._asset_tree.scrollTo(self._asset_tree.indexFromItem(sync_item_widget))
        asset_item_widget.setExpanded(True)
    

    def item_syncd(self, sync_item):
        """
        Handle signal from SyncWorker.progress to display sync status in sync_item_widget. 
        This sync_item_widget is looked up from our global asset dictionary using the signal payload arg [dict]
        """

        # log status of sync for this item
        asset_name = sync_item.get('asset_name')
        sync_path = sync_item.get("sync_path")
        response = sync_item.get('response')

        self.fw.log_debug(sync_path)

        # look up the sync-item object since we're passing only a topic/string around via signal
        child_widgets = self._asset_items[asset_name].get('child_widgets')
        sync_item_widget = child_widgets.get(sync_path)
        asset_item_widget = self._asset_items[asset_name].get('tree_widget')
        
        # since we're getting this                                                                
        icon  = self.make_icon("success")
        sync_item_widget.setIcon(1, icon)
        sync_item_widget.setText(1, "Syncd")

        # check how many asset children are still needing to be synced
        count_left_to_sync = len([sync_widget for sync_path,sync_widget in child_widgets.items() if sync_widget.text(1)=="Ready"])

        # set parent
        parent_asset_status = "{} item{} to sync"
        plurality = ""
        if count_left_to_sync > 0:
            if count_left_to_sync > 1:
                plurality = "s"

            # set asset parent's status regarding count-left-to-sync
            asset_item_widget.setText(1, parent_asset_status.format(count_left_to_sync, plurality))
        else:
            # when all sync's are done...
            icon  = self.make_icon("validate")
            asset_item_widget.setIcon(1, icon)
            asset_item_widget.setText(1,"Asset in Sync" )

        self.iterate_progress(message="Syncing {}".format(sync_item_widget.text(0)))


    def start_sync(self):
        """ 
        Iterate through assets and their sync items to start workers for all paths that require syncs. 
        Utilize a global threadpool to process
        """

        self._do.setEnabled(False)

        workers = []
        for asset_name, asset_dict in self._asset_items.items():
            for sync_path in asset_dict['child_widgets'].keys():
            
                sync_worker = SyncWorker()
                sync_worker.path_to_sync = sync_path
                sync_worker.asset_name = asset_name

                sync_worker.fw = self.fw
                
                sync_worker.started.connect(self.sync_in_progress)
                # worker.finished.connect(self.sync_completed)
                sync_worker.progress.connect(self.item_syncd)

                workers.append(sync_worker)
                
        self.progress = 0

        self.progress_maximum = len(workers)
        self._progress_bar.setRange(0, self.progress_maximum)
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)
        self._progress_bar.setFormat("%p%")

        # make threadpool to take all workers and multithread their execution
        self.threadpool = QtCore.QThreadPool.globalInstance()

        self.fw.log_debug("Starting Threaded P4 Sync...")

        # setup workers for multiprocessing

        for sync_worker in workers:
            self.threadpool.start(sync_worker)
