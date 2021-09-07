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

# file base for accessing Qt resources outside of resource scope
basepath = os.path.dirname(os.path.abspath(__file__))


class SyncSignaller(QtCore.QObject):
    started = QtCore.Signal(str)
    finished = QtCore.Signal()
    progress = QtCore.Signal(tuple) # (path to sync, p4 sync response)

class SyncWorker(QtCore.QRunnable):

    # structurally anticipate basic p4 calls, which will route to the main form. 
    p4 = None 
    fw = None
    path_to_sync = None

    def __init__(self):
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
        Ryn syncs from perforce. 
        """
        self.p4 = self.fw.connection.connect()

        self.fw.log_debug("starting thread in pool to sync {}".format(self.path_to_sync))
        self.started.emit(self.path_to_sync)
        # run the syncs
        p4_response = self.p4.run("sync", ["-f"], "{}#head".format(self.path_to_sync))

        self.fw.log_debug(p4_response)

        # emit item key and p4 response to main thread
        self.progress.emit((self.path_to_sync, p4_response))
        self.finished.emit()


class SyncForm(QtGui.QWidget):

    _fw = None
    _p4 = None
        
    progress = 0
    
    def __init__(self, assets_to_sync, parent=None):
        """
        Construction of sync UI
        """
        QtGui.QWidget.__init__(self, parent)

        self.assets_to_sync = assets_to_sync
        self._asset_items = {}
        self._sync_items = {}

        # creat UI elements and arrange them
        self.make_widgets()
        self.setup_ui()

        self.populate_assets()


    @property
    def fw(self):
        # implement framework if doesnt currently exist,  return it if it does
        if not self._fw:
            self._fw = sgtk.platform.current_bundle()
        return self._fw 

    @property
    def p4(self):
        # initializes p4 as connection setup if it doesnt exist. Passes existing if it does. 
        if not self._p4:
            self._p4 = self.fw.connection.connect()
        return self._p4

    def make_widgets(self):
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
        
        # set main layout
        self._main_layout = QtGui.QVBoxLayout()
        self.setLayout(self._main_layout)

        # hide progress until we run the sync
        self._progress_bar.setVisible(False)

        # asset tree setup
        self._asset_tree.setAnimated(True)
        self._asset_tree_header = QtGui.QTreeWidgetItem(["Asset Name","Status", "Details"])
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


    def populate_assets(self):

        self.asset_item_registry = {}  

        self.sync_items = {}
        self.sync_order = []

        # iterate all parent assets
        for index, item in enumerate(self.assets_to_sync):

            status_icon = "success"

            # grab asset info from our passed in asset list
            asset = item.get("asset")
            asset_name = asset.get('code')
            if not asset_name:
                asset_name = asset.get('name')
            status = "Ready to Sync"

            # if error was detected within the request step pre-ui: display it
            if item.get('error'):
                status_icon = "warning"
                status = "Error"

                # format sgtk exception as string to view
                detail = str(item.get('error'))
            else:
                detail = item.get('root_path')
            
            # only add first instance of parent asset (to only process depo trees once.)
            self.fw.log_debug("Adding item for {}".format(asset_name))

            if not self._asset_items.get(asset_name):
                
                # make top-level item. Register it so we dont keep making items for the same parent
                tree_item = QtGui.QTreeWidgetItem()
                self._asset_items[asset_name] = tree_item

                # simple list to keep track of eventual sync-items relating to this item 
                tree_item.sync_children = []

                # if asset item has a sgtk-created path to look for in the depot
                if item.get('root_path'):

                    # dry run the sync to see what is able to be sync'd
                    sync_response = self.p4.run("sync", ["-n", "-f"], "{}".format(item.get('root_path')))
                    self.fw.log_debug("P4 log:" + str(sync_response))

                    # if nothing returned in sync dry-run, nothing required to sync
                    if not sync_response:
                        status = "Not In Depot"
                        status_icon = "error"
                        detail = "Nothing in depot resolves [{}]".format(item.get('root_path'))
                    else:
                        # if the response from p4 has items... make UI elements for them
                        status = "{} items to Sync".format(len(sync_response))
                        status_icon = "load"

                        for p4_item in sync_response:
                            if type(p4_item)==dict:
                                sync_item = QtGui.QTreeWidgetItem(tree_item)
                                sync_item.setText(1, "Ready")
                                sync_item.setText(2, p4_item.get("clientFile"))
                                sync_item_icon = QtGui.QIcon(os.path.join(basepath, 
                                                                        'resources', 
                                                                        "status_load.png"))
                                sync_item.setIcon(1, sync_item_icon)
                                sync_item.setText(0, p4_item.get("clientFile").split(os.sep)[-1])

                                sync_item.asset_parent = tree_item

                                tree_item.sync_children.append(sync_item)

                                self.sync_items[p4_item.get("clientFile")] = sync_item
                                self.sync_order.append(p4_item.get("clientFile"))
                            else:
                                self.fw.log_debug("P4 Response is str:: " + str(p4_item))

                # store data against the object for when we use sync command   
                tree_item.asset_name = asset_name
                tree_item.asset_status = status
                tree_item.asset_index = index

                # set text fields on the asset tree item
                tree_item.setText(0, asset_name )
                tree_item.setText(1, status)
                tree_item.setText(2, detail )

                # set icon based on status
                item_icon = self.make_icon(status_icon)
                tree_item.setIcon(1, item_icon)

                # newline the errors for easier tooltip reading
                tree_item.setToolTip(2, detail.replace(". ", ".\n"))

    
        # sort the list, then populate items into the tree
        asset_item_display_list = sorted([item for name, item in self._asset_items.items()], 
                                            key=lambda k: (k.asset_status.lower(), k.asset_index ), reverse=True) 
        for item in asset_item_display_list:
            self._asset_tree.addTopLevelItem(item)

    def make_icon(self, name):
        return QtGui.QIcon(os.path.join(basepath, 'resources', "status_{}.png".format(name)))

    def populate_list(self):
        for item in self.assets_to_sync:
            self._list.addItem( str(item) )
        

    def sync_in_progress(self, sync_path):
        item = self.sync_items.get(sync_path)
        icon  = self.make_icon("syncing")
        item.setIcon(1, icon)
        item.setText(1, "Syncing")

    def item_syncd(self, sync_item):
        try:
            # log status of sync for this item
            self.fw.log_debug(sync_item[1])

            # look up the sync-item object since we're passing only a topic/string around via signal
            item = self.sync_items.get(sync_item[0])
            item_name = sync_item[0]

            # since we're getting this                                                                
            icon  = self.make_icon("success")
            item.setIcon(1, icon)
            item.setText(1, "Syncd")

            # check how many asset children are still needing to be synced
            count_left_to_sync = len([i for i in item.asset_parent.sync_children if i.text(1)=="Ready"])

            # set parent
            parent_asset_status = "{} item{} to sync"
            plurality = ""
            if count_left_to_sync > 0:
                if count_left_to_sync > 1:
                    plurality = "s"

                # set asset parent's status regarding count-left-to-sync
                item.asset_parent.setText(1, parent_asset_status.format(count_left_to_sync, plurality))
            else:
                # when all sync's are done...
                icon  = self.make_icon("validate")
                item.asset_parent.setIcon(1, icon)
                item.asset_parent.setText(1,"Asset in Sync" )

            # keep the sync-item in view
            self._asset_tree.scrollTo(self._asset_tree.indexFromItem(item))
            item.asset_parent.setExpanded(True)

            # iterate progress
            self.progress += 1
            self._progress_bar.setValue(self.progress)
            self._progress_bar.setFormat("Syncing {} %p%".format(item_name))
        except Exception as e:
            self.fw.log_info(e)


    def start_sync(self):

        self.progress = 0

        self.progress_maximum = len(self.sync_order)
        self._progress_bar.setRange(0, self.progress_maximum)
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)


        # make threadpool to take all workers and multithread their execution
        self.threadpool = QtCore.QThreadPool.globalInstance()

        self.fw.log_debug("Starting Threaded P4 Sync...")

        # setup workers for multiprocessing
        for path in self.sync_items:
            
            worker = SyncWorker()
            worker.path_to_sync = path

            worker.fw = self.fw
            
            # turn the below on to share the p4 connection. 
            # worker.p4 = self.p4

            worker.started.connect(self.sync_in_progress)
            # worker.finished.connect(self.sync_completed)
            worker.progress.connect(self.item_syncd)

            self.threadpool.start(worker)
            self.fw.log_debug("Sync for {} started on new worker thread.".format(path))

    
    def sync_completed(self):
        self._progress_bar.setFormat("Sync complete %p%")
        self._progress_bar.setVisible(False)