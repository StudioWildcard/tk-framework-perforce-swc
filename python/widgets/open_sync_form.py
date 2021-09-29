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

from .sync_workers import SyncWorker, AssetInfoGatherWorker
from .utils import PrefFile

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

        self.parent = parent

        self.app = parent_sgtk_app
        self.entities_to_sync = entities_to_sync

        self._asset_item_info = {}
        self._asset_items = {}
        self._sync_items = {}
        self._step_options = []
        self._step_actions = {}
        self._filtered_away = []

        self.prefs = PrefFile()

        self.threadpool = QtCore.QThreadPool.globalInstance()

        # creat UI elements and arrange them
        self.make_widgets()
        self.setup_ui()

        # add assets and what we want to sync into the view
        if self.entities_to_sync:
            self.populate_assets()
        else:
            self._do.setVisible(False)
            self._asset_tree.setVisible(False)
            self._progress_bar.setRange(0, 1)
            self._progress_bar.setValue(0)
            self.set_progress_message("Please use Perforce Sync with a chosen context. None detected.", percentf=" ")

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

        self._step_filter_label = QtGui.QLabel("Show/Sync Steps:")
        self._hide_syncd = QtGui.QCheckBox()
        self._step_filter = QtGui.QToolButton()
        self._step_menu = QtGui.QMenu()
        

    def setup_ui(self):
        """
        Lays out and customizes widgets for the main form
        """       
        # set main layout
        self._main_layout = QtGui.QVBoxLayout()
        self._menu_layout = QtGui.QHBoxLayout()

        self._main_layout.addLayout(self._menu_layout)
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

        self._hide_syncd.setText("Hide if nothing to sync")
        self._hide_syncd.stateChanged.connect(self.save_ui_state)
        self._hide_syncd.stateChanged.connect(self.filter_syncd_items )
        self._hide_syncd.setChecked(self.prefs.data.get('hide_syncd'))

        self._step_filter.setMinimumWidth(90)
        self._step_menu.setMinimumWidth(90)
        self._step_filter.setText("Step Filters")
        self._step_filter.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self._step_filter.setMenu(self._step_menu)
        self._step_filter.setPopupMode(QtGui.QToolButton.InstantPopup)
        self._step_menu.setTearOffEnabled(True)
        
        self._menu_layout.addWidget(self._hide_syncd)
        
        self._menu_layout.addStretch()
        #self._menu_layout.addWidget(self._step_filter_label)
        self._menu_layout.addWidget(self._step_filter)
        

        # arrange widgets in layout
        self._main_layout.addWidget( self._asset_tree)
        self._main_layout.addWidget(self._progress_bar)
        self._main_layout.addWidget(self._do)

        # css
        self.setStyleSheet("""
            QTreeWidget::item { padding: 5px; }
            QAction  { padding: 10px; }
        """ )
        
        # signal connections
        self._do.clicked.connect(self.start_sync)

        width, height = self.prefs.data.get('window_size')
        self.parent.resize(width, height)

        self.set_ui_interactive(False)

    def resizeEvent( self, event ):
        """
        Keep track of window_size
        """
        QtGui.QWidget.resizeEvent( self, event )
        self.save_ui_state()


    def save_ui_state(self):
        """
        Sync UI state and prefs locally to use for persistent UI features
        """
        data = self.prefs.read()
        data["hide_syncd"] = self._hide_syncd.isChecked()

        step_filters = {}
        if data.get('step_filters'):
            step_filters = data.get('step_filters')
        for k,v in self._step_actions.items():
            step_filters[k] = v.isChecked()
        data['step_filters'] = step_filters
        data['window_size'] = [self.width(), self.height()]
        self.prefs.write(data)

    def filter_syncd_items(self):
        """
        Filter top-level items if theyre already sync'd
        """
        try:
            
            hide_syncd_checkstate = self._hide_syncd.isChecked()

            for asset_name, asset_dict in self._asset_items.items():
                asset_status = asset_dict.get('status')
                if asset_status == "Syncd":

                    tree_item = asset_dict.get("tree_widget")
                    tree_item.setHidden(hide_syncd_checkstate)
                
        except Exception as e:
            self.fw.log_info(str(e))


    def filter_step_items(self):
        """
        Filter sync items away based on the step check-boxes
        """
        try:
            self._filtered_away = []
            self.prefs.read()
            step_filters = self.prefs.data.get('step_filters')

            for asset_name, asset_dict in self._asset_items.items():

                if asset_dict.get('status') != "Syncd":
                
                    for sync_path, sync_widget in asset_dict['child_widgets'].items():
                        step = asset_dict['child_steps'].get(sync_path)

                        if step in step_filters.keys():
                            
                            sync_widget.setHidden(not step_filters.get(step))

                            # keep track for user of what isnt being shown to them
                            if (not step_filters.get(step)) is True:
                                self._filtered_away.append(sync_path)

                    self.update_sync_counter(asset_name) 

            # indicate to user that items being filtered from view
            if len(self._filtered_away) > 0:
                self._step_filter.setIcon(self.make_icon("filter"))
            else:
                self._step_filter.setIcon(QtGui.QIcon())     

        except Exception as e:
            self.fw.log_info(str(e))

    def set_ui_interactive(self, state):
        """
        Common utility to lock the UI while info-gathering or syncing is occuring
        """
        self._step_filter.setEnabled(state)
        self._hide_syncd.setEnabled(state)
        self._do.setEnabled(state)

    def update_sync_counter(self, asset_name):
        """
        Update the top-level count of how many items there are to sync for an asset upon filters being applied
        """
        asset_dict = self._asset_items.get(asset_name)
        tree_widget = asset_dict.get("tree_widget")
        unfiltered_sync_count = len(asset_dict.get('child_widgets').keys())
        items_to_sync = [i for i,w in asset_dict.get('child_widgets').items() if not w.isHidden()]

        count_to_sync = len(items_to_sync)

        parent_asset_status = "{} item{} to sync"
        plurality = ""
        if count_to_sync > 0:
            if count_to_sync > 1:
                plurality = "s"

            # set asset parent's status regarding count-left-to-sync
            tree_widget.setText(1, parent_asset_status.format(count_to_sync, plurality))
            tree_widget.setIcon(1, self.make_icon('load'))
        else:
            tree_widget.setText(1, "{} Files filtered".format(unfiltered_sync_count-count_to_sync))
            tree_widget.setIcon(1, self.make_icon('validate'))


    def update_steps_available(self, step):
        """
        Populate the steps filter menu as steps are discovered in the p4 scan search
        """
        try:
            if step not in self._step_actions.keys():
                action = QtGui.QAction(self)
                
                action.setCheckable(True)

                self.prefs.read()
                step_filters = self.prefs.data.get('step_filters')
                check_state = True
                if step in step_filters.keys():
                    check_state = step_filters[step]
                

                action.setChecked(check_state)
                action.setText(str(step))
                action.triggered.connect(self.save_ui_state)
                action.triggered.connect(self.filter_step_items)

                self._step_menu.addAction(action)
        
                self._step_actions[step] = action
        except Exception as e:
            self.fw.log_info(str(e))

    def make_top_level_tree_item(self, asset_name=None, status=None, details=None, icon=None):
        """
        Creates QTreeWidgetItem to display asset information
        """
        tree_item = QtGui.QTreeWidgetItem(self._asset_tree)

        # if user has chosen to not see these 
        if self._hide_syncd.isChecked() and status == "Syncd":
            tree_item.setHidden(True)

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
        step = sync_item_info.get('step')

        tree_item = self._asset_items[asset_name].get("tree_widget")

        child_tree_item = QtGui.QTreeWidgetItem(tree_item)

        asset_file_path = item_found.get('clientFile') 
        asset_file_name = os.path.basename(item_found.get('clientFile'))

        if step:
            step_filters = self.prefs.data.get('step_filters')
            if step in step_filters.keys():
                child_tree_item.setHidden(not step_filters.get(step))
            

        child_tree_item.setText(self.ASSET_NAME, asset_file_name) #If it is not clientFile specifically it seems like the name is within that info at least the correct wording is probably in clientFile
        child_tree_item.setText(self.STATUS, "Ready")
        child_tree_item.setText(self.DETAIL, asset_file_path) #after testing it works as intended but we need to link it to the actual names the correct wording is probably in depotFile
        child_tree_item.setIcon(self.STATUS, self.make_icon("load"))

        child_steps = self._asset_items[asset_name].get("child_steps")  
        child_steps[asset_file_path] = step
        
        child_widgets = self._asset_items[asset_name].get("child_widgets")
        child_widgets[ asset_file_path ] = child_tree_item

        self.update_sync_counter(asset_name)

        

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
        asset_UI_mapping['status'] = info_processed_dict.get("status")
        asset_UI_mapping['child_widgets'] = {}
        asset_UI_mapping['child_steps'] = {}

        self._asset_items[info_processed_dict.get("asset_name")] = asset_UI_mapping
        

    def set_progress_message(self, message=None, percentf=" %p%"):
        """
        Set the message to see in the progress bar
        """
        self._progress_bar.setVisible(True)
        self._progress_bar.setFormat("{}{}".format(message, percentf))


    def iterate_progress(self, message=None):
        """
        Iterate global progress counter and update the progressbar widget
        Detect if progress is globally complete and handle hiding the progress widget
        """
        self._progress_bar.setVisible(True)
        self.progress += 1
        
        self._progress_bar.setValue(self.progress)
        self.set_progress_message(message)
        if self._progress_bar.value() == self._progress_bar.maximum():
            self.set_progress_message("{} complete".format(message))
            self._progress_bar.setVisible(False)

            self.set_ui_interactive(True)

            self.filter_step_items()


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

        # self.fw.log_info(len(self.entities_to_sync))
        # iterate all parent assets
        for entity_to_sync in self.entities_to_sync:

            asset_info_gather_worker = AssetInfoGatherWorker(app=self.app,
                                                             entity=entity_to_sync,
                                                             framework=self.fw)

            asset_info_gather_worker.info_gathered.connect( self.asset_info_handler )
            asset_info_gather_worker.progress.connect( self.iterate_progress )
            asset_info_gather_worker.item_found_to_sync.connect(self.make_sync_tree_item)
            asset_info_gather_worker.status_update.connect(self.set_progress_message)
            asset_info_gather_worker.include_step.connect(self.update_steps_available)

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

        # self.fw.log_debug(sync_path)

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

        self.set_ui_interactive(False)

        workers = []
        for asset_name, asset_dict in self._asset_items.items():
            for sync_path, sync_widget in asset_dict['child_widgets'].items():
                if not sync_widget.isHidden():
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
