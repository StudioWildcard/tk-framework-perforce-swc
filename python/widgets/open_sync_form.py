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
import sys
import urllib

from functools import partial

from .sync_workers import SyncWorker, AssetInfoGatherWorker
from .utils import PrefFile, open_browser
# standard toolkit logger
logger = sgtk.platform.get_logger(__name__)
#from .loader_utils import resolve_filters

from .model_status import SgStatusModel
from .model_latestpublish import SgLatestPublishModel
from .model_publishhistory import SgPublishHistoryModel
from .delegate_publish_history import SgPublishHistoryDelegate

from .loader_action_manager import LoaderActionManager

# file base for accessing Qt resources outside of resource scope
basepath = os.path.dirname(os.path.abspath(__file__))

logger.info(">>>>>>  tk-framework-shotgunutil, shotgun_model")

# import frameworks
shotgun_model = sgtk.platform.import_framework(
    "tk-framework-shotgunutils", "shotgun_model"
)
settings = sgtk.platform.import_framework("tk-framework-shotgunutils", "settings")
help_screen = sgtk.platform.import_framework("tk-framework-qtwidgets", "help_screen")
overlay_widget = sgtk.platform.import_framework(
    "tk-framework-qtwidgets", "overlay_widget"
)
shotgun_search_widget = sgtk.platform.import_framework(
    "tk-framework-qtwidgets", "shotgun_search_widget"
)
task_manager = sgtk.platform.import_framework(
    "tk-framework-shotgunutils", "task_manager"
)
shotgun_globals = sgtk.platform.import_framework(
    "tk-framework-shotgunutils", "shotgun_globals"
)

ShotgunModelOverlayWidget = overlay_widget.ShotgunModelOverlayWidget

class SyncForm(QtGui.QWidget):

    _fw = None
    _p4 = None
        
    progress = 0
    selection_changed = QtCore.Signal()
    def __init__(self, parent_sgtk_app, entities_to_sync, specific_files,  parent=None):
        """
        Construction of sync UI
        """
        QtGui.QWidget.__init__(self, parent)

        self.parent = parent

        self.app = parent_sgtk_app
        self.entities_to_sync = entities_to_sync
        self.specific_files= specific_files

        self._action_manager = LoaderActionManager()
        # self._action_manager = None

        self._sg_data = {}
        self._key = None
        self.scan()

        # create a background task manager
        self._task_manager = task_manager.BackgroundTaskManager(
            self, start_processing=True, max_threads=2
        )
        shotgun_globals.register_bg_task_manager(self._task_manager)

        # hook a helper model tracking status codes so we
        # can use those in the UI
        self._status_model = SgStatusModel(self, self._task_manager)

        self.init_details_panel()




    def log_error(self, e):
        self.fw.log_error(str(e))
        self.fw.log_error(traceback.format_exc())

    def scan(self):
        self._asset_item_info = {}
        self._asset_items = {}
        self._sync_items = {}
        self._step_options = []

        self._filtered_away = []

        self.use_filters = ['Step', 'Type', 'Ext']
        self.filter_sizes = {
            "Step" : 80,
            "Type" : 130,
            "Ext" : 50
        }

        # init preferences
        self.prefs = PrefFile()
        if not self.prefs.data.get('hide_syncd'):
            self.prefs.data['hide_syncd'] = True
            self.prefs.write()
            self.prefs.read()

        # if not self.prefs.data.get('force_sync'):
        #     self.prefs.data['force_sync'] = False
        #     self.prefs.write()
        #     self.prefs.read()
        self.threadpool = QtCore.QThreadPool.globalInstance()
        self.threadpool.setMaxThreadCount(min(24, self.threadpool.maxThreadCount()))

        # creat UI elements and arrange them
        self.make_widgets()
        self.setup_ui()

        # add assets and what we want to sync
        # into the view
        if self.entities_to_sync:
            self.populate_assets()
        else:
            self._do.setVisible(False)
            self._asset_tree.setVisible(False)
            self._progress_bar.setRange(0, 1)
            self._progress_bar.setValue(0)
            self.set_progress_message("Please use Perforce Sync with a chosen context. None detected.", percentf=" ")

    def rescan(self):
        self._asset_tree.clear()
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

        self._asset_tree.clear()
        self._progress_bar = QtGui.QProgressBar()
        self._list = QtGui.QListWidget()
        self._line_edit = QtGui.QLineEdit()
        self._line_edit.setText(" ")

        self._step_filter_label = QtGui.QLabel("Show/Sync Steps:")
        self._hide_syncd = QtGui.QCheckBox()

        self._force_sync = QtGui.QCheckBox()
        self._force_sync.setText("Force Sync")

        self._rescan = QtGui.QPushButton("Rescan")


    def setup_ui(self):
        """
        Lays out and customizes widgets for the main form
        """

        self.resize(1200, 800)

        # set main layout
        self._gui_layout = QtGui.QHBoxLayout()
        self._main_layout = QtGui.QVBoxLayout()
        self._menu_layout = QtGui.QHBoxLayout()

        #self.setLayout(self._main_layout)
        self.setLayout(self._gui_layout)

        # hide progress until we run the sync
        self._progress_bar.setVisible(False)

        # asset tree setup
        self.tree_header = ["Asset Name", "Status", "Version", "Detail"]
        for h in self.tree_header:
            setattr(self, h.replace(' ', "_").upper(), self.tree_header.index(h))

        self._asset_tree.setAnimated(True)
        self._asset_tree_header = QtGui.QTreeWidgetItem(self.tree_header)
        self._asset_tree.setHeaderItem(self._asset_tree_header)  
        self._asset_tree.setWordWrap(True)
        self._asset_tree.setColumnWidth(0, 150)
        self._asset_tree.setColumnWidth(1, 120)
        self._asset_tree.setColumnWidth(2, 50)

        self._hide_syncd.setText("Hide if nothing to sync")
        self._hide_syncd.stateChanged.connect(self.save_ui_state)
        self._hide_syncd.stateChanged.connect(self.filter_syncd_items )
        self._hide_syncd.setChecked(self.prefs.data.get('hide_syncd'))

        self._force_sync.stateChanged.connect(self.save_ui_state)
        self._force_sync.stateChanged.connect(self.rescan)
        self._force_sync.setChecked(self.prefs.data.get('force_sync'))


        self._menu_layout.addWidget(self._hide_syncd)
        self._menu_layout.addStretch()
        #self._menu_layout.addWidget(self._step_filter_label)

        self.sync_layout = QtGui.QHBoxLayout()
        self.sync_layout.addWidget(self._rescan,  3)
        self.sync_layout.addWidget(self._do,  10)
        self.sync_layout.addWidget(self._force_sync, 1)

        # arrange widgets in layout
        self._main_layout.addLayout(self._menu_layout)
        self._main_layout.addWidget( self._asset_tree)
        self._main_layout.addWidget(self._progress_bar)
        self._main_layout.addLayout(self.sync_layout)

        # details layout
        self.details_layout = QtGui.QVBoxLayout()
        self.details_layout.setSpacing(2)
        self.details_layout.setContentsMargins(4, 4, 4, 4)
        self.details_layout.setObjectName("details_layout")

        self.horizontalLayout = QtGui.QHBoxLayout()
        self.horizontalLayout.setObjectName("horizontalLayout")
        spacerItem2 = QtGui.QSpacerItem(40, 20, QtGui.QSizePolicy.Expanding, QtGui.QSizePolicy.Minimum)
        self.horizontalLayout.addItem(spacerItem2)
        self.details_image = QtGui.QLabel()
        sizePolicy = QtGui.QSizePolicy(QtGui.QSizePolicy.Fixed, QtGui.QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.details_image.sizePolicy().hasHeightForWidth())
        self.details_image.setSizePolicy(sizePolicy)
        self.details_image.setMinimumSize(QtCore.QSize(256, 200))
        self.details_image.setMaximumSize(QtCore.QSize(256, 200))
        self.details_image.setScaledContents(True)
        self.details_image.setAlignment(QtCore.Qt.AlignCenter)
        self.details_image.setObjectName("details_image")
        self.horizontalLayout.addWidget(self.details_image)
        spacerItem3 = QtGui.QSpacerItem(40, 20, QtGui.QSizePolicy.Expanding, QtGui.QSizePolicy.Minimum)
        self.horizontalLayout.addItem(spacerItem3)
        self.details_layout.addLayout(self.horizontalLayout)

        self.horizontalLayout_5 = QtGui.QHBoxLayout()
        self.horizontalLayout_5.setObjectName("horizontalLayout_5")
        self.details_header = QtGui.QLabel()
        self.details_header.setAlignment(QtCore.Qt.AlignLeading | QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        self.details_header.setWordWrap(True)
        self.details_header.setObjectName("details_header")
        self.horizontalLayout_5.addWidget(self.details_header)
        spacerItem4 = QtGui.QSpacerItem(40, 20, QtGui.QSizePolicy.Expanding, QtGui.QSizePolicy.Minimum)
        self.horizontalLayout_5.addItem(spacerItem4)
        self.verticalLayout_4 = QtGui.QVBoxLayout()
        self.verticalLayout_4.setObjectName("verticalLayout_4")
        self.detail_playback_btn = QtGui.QToolButton()
        self.detail_playback_btn.setMinimumSize(QtCore.QSize(55, 55))
        self.detail_playback_btn.setMaximumSize(QtCore.QSize(55, 55))
        self.detail_playback_btn.setText("")
        icon4 = QtGui.QIcon()
        icon4.addPixmap(QtGui.QPixmap(":/res/play_icon.png"), QtGui.QIcon.Normal, QtGui.QIcon.Off)
        self.detail_playback_btn.setIcon(icon4)
        self.detail_playback_btn.setIconSize(QtCore.QSize(40, 40))
        self.detail_playback_btn.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.detail_playback_btn.setObjectName("detail_playback_btn")
        self.detail_playback_btn.setToolTip("The most recent published version has some playable media associated. Click this button to launch the ShotGrid <b>Media Center</b> web player to see the review version and any notes and comments that have been submitted.")

        self.verticalLayout_4.addWidget(self.detail_playback_btn)
        self.detail_actions_btn = QtGui.QToolButton()
        self.detail_actions_btn.setMinimumSize(QtCore.QSize(55, 0))
        self.detail_actions_btn.setMaximumSize(QtCore.QSize(55, 16777215))
        self.detail_actions_btn.setPopupMode(QtGui.QToolButton.InstantPopup)
        self.detail_actions_btn.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
        self.detail_actions_btn.setObjectName("detail_actions_btn")
        self.detail_actions_btn.setText("Actions")
        self.verticalLayout_4.addWidget(self.detail_actions_btn)

        self.horizontalLayout_5.addLayout(self.verticalLayout_4)
        self.details_layout.addLayout(self.horizontalLayout_5)

        self.version_history_label = QtGui.QLabel()
        sizePolicy = QtGui.QSizePolicy(QtGui.QSizePolicy.Preferred, QtGui.QSizePolicy.Maximum)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.version_history_label.sizePolicy().hasHeightForWidth())
        self.version_history_label.setSizePolicy(sizePolicy)
        self.version_history_label.setStyleSheet("QLabel { padding-top: 14px}")
        self.version_history_label.setAlignment(QtCore.Qt.AlignCenter)
        self.version_history_label.setWordWrap(True)
        self.version_history_label.setObjectName("version_history_label")
        self.version_history_label.setText("<small>Complete Version History</small>")
        #self.version_history_label.setText(QtGui.QApplication.translate("Dialog", "<small>Complete Version History</small>", None, QtGui.QApplication.UnicodeUTF8))
        self.details_layout.addWidget(self.version_history_label)

        self.history_view = QtGui.QListView()
        self.history_view.setVerticalScrollMode(QtGui.QAbstractItemView.ScrollPerPixel)
        self.history_view.setHorizontalScrollMode(QtGui.QAbstractItemView.ScrollPerPixel)
        self.history_view.setUniformItemSizes(True)
        self.history_view.setObjectName("history_view")
        self.details_layout.addWidget(self.history_view)

        self.container_widget = QtGui.QWidget()
        self.container_widget.setLayout(self.details_layout)
        self.container_widget.setFixedWidth(300)

        # arrange widgets in gui layout
        self._gui_layout.addLayout(self._main_layout)
        # self._gui_layout.addLayout(self.details_layout)
        self._gui_layout.addWidget(self.container_widget)

        # css
        self.setStyleSheet("""
            QTreeWidget::item { padding: 5px; }
            QAction  { padding: 10px; }
        """ )
        
        # signal connections
        self._do.clicked.connect(self.start_sync)

        for f in self.use_filters:
            self.button_menu_factory(f)

        # Add info button
        self.info = QtGui.QToolButton()
        self.info.setMinimumSize(QtCore.QSize(80, 26))
        self.info.setObjectName("info")
        self.info.setToolTip("Use this button to <i>toggle details on and off</i>.")
        #self.info.setText("Show Details")
        self.info.setText("Hide Details")
        self._menu_layout.addWidget(self.info)

        # Single click on tree item
        self._asset_tree.itemClicked.connect(self.on_item_clicked)

        # connect right_click_menu to tree
        self._asset_tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self._asset_tree.customContextMenuRequested.connect(self.open_context_menu)

        self._rescan.clicked.connect(self.rescan)
        self.set_ui_interactive(False)

        if self.specific_files:
            self._rescan.setVisible(False)
            self._force_sync.setVisible(False)

    def init_details_panel(self):

        # details pane
        # self._details_pane_visible = False
        self._details_pane_visible = True

        self._details_action_menu = QtGui.QMenu()
        self.detail_actions_btn.setMenu(self._details_action_menu)

        self.info.clicked.connect(self._toggle_details_pane)


        self._publish_history_model = SgPublishHistoryModel(self, self._task_manager)

        self._publish_history_model_overlay = ShotgunModelOverlayWidget(
            self._publish_history_model, self.history_view
        )

        self._publish_history_proxy = QtGui.QSortFilterProxyModel(self)
        self._publish_history_proxy.setSourceModel(self._publish_history_model)

        # now use the proxy model to sort the data to ensure
        # higher version numbers appear earlier in the list
        # the history model is set up so that the default display
        # role contains the version number field in shotgun.
        # This field is what the proxy model sorts by default
        # We set the dynamic filter to true, meaning QT will keep
        # continously sorting. And then tell it to use column 0
        # (we only have one column in our models) and descending order.
        self._publish_history_proxy.setDynamicSortFilter(True)
        self._publish_history_proxy.sort(0, QtCore.Qt.DescendingOrder)

        self.history_view.setModel(self._publish_history_proxy)

        self._history_delegate = SgPublishHistoryDelegate(
            self.history_view, self._status_model, self._action_manager
        )
        self.history_view.setItemDelegate(self._history_delegate)

        # event handler for when the selection in the history view is changing
        # note! Because of some GC issues (maya 2012 Pyside), need to first establish
        # a direct reference to the selection model before we can set up any signal/slots
        # against it
        self._history_view_selection_model = self.history_view.selectionModel()
        self._history_view_selection_model.selectionChanged.connect(
            self._on_history_selection
        )

        self._multiple_publishes_pixmap = QtGui.QPixmap(
            ":/res/multiple_publishes_512x400.png"
        )
        self._no_selection_pixmap = QtGui.QPixmap(":/res/no_item_selected_512x400.png")
        self._no_pubs_found_icon = QtGui.QPixmap(":/res/no_publishes_found.png")

        self.detail_playback_btn.clicked.connect(self._on_detail_version_playback)
        self._current_version_detail_playback_url = None

        # set up right click menu for the main publish view
        self._refresh_history_action = QtGui.QAction("Refresh", self.history_view)
        self._refresh_history_action.triggered.connect(
            self._publish_history_model.async_refresh
        )
        self.history_view.addAction(self._refresh_history_action)
        self.history_view.setContextMenuPolicy(QtCore.Qt.ActionsContextMenu)

        # if an item in the list is double clicked the default action is run
        self.history_view.doubleClicked.connect(self._on_history_double_clicked)



    def button_menu_factory(self, name= None ):

        width = 80
        short_name = name.lower().replace(" ", "")
        if name in self.filter_sizes.keys():
            width = self.filter_sizes.get(name)

        setattr(self, "_{}_filter".format(short_name), QtGui.QToolButton())
        setattr(self, "_{}_menu".format(short_name), QtGui.QMenu())
        setattr(self, "_{}_actions".format(short_name), {})

        btn = getattr(self, "_{}_filter".format(short_name))
        menu = getattr(self, "_{}_menu".format(short_name))
       
        btn.setFixedWidth(width) 
        btn.setText(name)
        btn.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        btn.setMenu(menu)
        btn.setPopupMode(QtGui.QToolButton.InstantPopup)

        menu.setFixedWidth(width)
        menu.setTearOffEnabled(True)

        self._menu_layout.addWidget(btn)


    def resizeEvent( self, event ):
        """
        Keep track of window_size
        """
        QtGui.QWidget.resizeEvent( self, event )
        self.save_ui_state()

    def _toggle_details_pane(self):
        """
        Executed when someone clicks the show/hide details button
        """
        if self.container_widget.isVisible():
            self._set_details_pane_visiblity(False)
        else:
            self._set_details_pane_visiblity(True)

    def _set_details_pane_visiblity(self, visible):
        """
        Specifies if the details pane should be visible or not
        """
        # store our value in a setting
        #self._settings_manager.store("show_details", visible)

        if visible == False:
            # hide details pane
            self._details_pane_visible = False
            self.container_widget.setVisible(False)
            self.info.setText("Show Details")

        else:
            # show details pane
            self._details_pane_visible = True
            self.container_widget.setVisible(True)
            self.info.setText("Hide Details")


            # if there is something selected, make sure the detail
            # section is focused on this
            self._setup_details_panel(self._key)

    def _setup_details_panel(self, key):
        """
        Sets up the details panel with info for a given item.
        """

        def __make_table_row(left, right):
            """
            Helper method to make a detail table row
            """
            return (
                    "<tr><td><b style='color:#2C93E2'>%s</b>&nbsp;</td><td>%s</td></tr>"
                    % (left, right)
            )

        def __set_publish_ui_visibility(is_publish):
            """
            Helper method to enable disable publish specific details UI
            """
            # disable version history stuff
            self.version_history_label.setEnabled(is_publish)
            self.history_view.setEnabled(is_publish)

            # hide actions and playback stuff
            self.detail_actions_btn.setVisible(is_publish)
            self.detail_playback_btn.setVisible(is_publish)

        def __clear_publish_history(pixmap):
            """
            Helper method that clears the history view on the right hand side.

            :param pixmap: image to set at the top of the history view.
            """
            self._publish_history_model.clear()
            self.details_header.setText("")
            self.details_image.setPixmap(pixmap)
            __set_publish_ui_visibility(False)

        # note - before the UI has been shown, querying isVisible on the actual
        # widget doesn't work here so use member variable to track state instead
        if not self._details_pane_visible:
            return

        if not key:
            __clear_publish_history(self._no_selection_pixmap)

        if key and key not in self._sg_data:
            __clear_publish_history(self._no_pubs_found_icon)
            self.fw.log_info("Unable to find {} in SG data. Perhaps, item is not published".format(key))

        if key and key in self._sg_data:

            # render out details
            #thumb_pixmap = item.icon().pixmap(512)
            if "image" in self._sg_data[key]:
                #thumb_pixmap = self._sg_data[key]["image"]
                #self.details_image.setPixmap(thumb_pixmap)
                image_url = self._sg_data[key]["image"]
                file_path = "C:/temp/tmp.png"
                urllib.request.urlretrieve(image_url, file_path)
                self.details_image.setPixmap(QtGui.QPixmap(file_path))

            sg_data = self._sg_data[key]

            if sg_data is None:
                # an item which doesn't have any sg data directly associated
                # typically an item higher up the tree
                # just use the default text
                if "name" in sg_data:
                    folder_name = __make_table_row("Name", sg_data.get("name"))
                    self.details_header.setText("<table>%s</table>" % folder_name)
                    __set_publish_ui_visibility(False)

                """
                elif item.data(SgLatestPublishModel.IS_FOLDER_ROLE):
                    # folder with sg data - basically a leaf node in the entity tree
    
                    status_code = sg_data.get("sg_status_list")
                    if status_code is None:
                        status_name = "No Status"
                    else:
                        status_name = self._status_model.get_long_name(status_code)
    
                    status_color = self._status_model.get_color_str(status_code)
                    if status_color:
                        status_name = (
                                "%s&nbsp;<span style='color: rgb(%s)'>&#9608;</span>"
                                % (status_name, status_color)
                        )
    
                    if sg_data.get("description"):
                        desc_str = sg_data.get("description")
                    else:
                        desc_str = "No description entered."
    
                    msg = ""
                    display_name = shotgun_globals.get_type_display_name(sg_data["type"])
                    msg += __make_table_row(
                        "Name", "%s %s" % (display_name, sg_data.get("code"))
                    )
                    msg += __make_table_row("Status", status_name)
                    msg += __make_table_row("Description", desc_str)
                    self.details_header.setText("<table>%s</table>" % msg)
    
                    # blank out the version history
                    __set_publish_ui_visibility(False)
                    self._publish_history_model.clear()
                """
            else:
                # this is a publish!
                __set_publish_ui_visibility(True)

                sg_item = self._sg_data[key]

                # sort out the actions button
                actions = self._action_manager.get_actions_for_publish(
                    sg_item, self._action_manager.UI_AREA_DETAILS
                )
                if len(actions) == 0:
                    self.detail_actions_btn.setVisible(False)
                else:
                    self.detail_playback_btn.setVisible(True)
                    self._details_action_menu.clear()
                    for a in actions:
                        self._dynamic_widgets.append(a)
                        self._details_action_menu.addAction(a)

                # if there is an associated version, show the play button
                if sg_item.get("version"):
                    sg_url = sgtk.platform.current_bundle().shotgun.base_url
                    url = "%s/page/media_center?type=Version&id=%d" % (
                        sg_url,
                        sg_item["version"]["id"],
                    )

                    self.detail_playback_btn.setVisible(True)
                    self._current_version_detail_playback_url = url

                else:
                    self.detail_playback_btn.setVisible(False)
                    self._current_version_detail_playback_url = None

                if sg_item.get("name") is None:
                    name_str = "No Name"
                else:
                    name_str = sg_item.get("name")

                #type_str = shotgun_model.get_sanitized_data(
                #    #item, SgLatestPublishModel.PUBLISH_TYPE_NAME_ROLE
                #    sg_item.get("type"), SgLatestPublishModel.PUBLISH_TYPE_NAME_ROLE
                #)

                if "published_file_type" in sg_item and "name" in sg_item["published_file_type"]:
                    type_str = sg_item["published_file_type"]["name"]
                else:
                    type_str = sg_item.get("type")
                msg = ""
                msg += __make_table_row("Name", name_str)
                msg += __make_table_row("Type", type_str)

                version = sg_item.get("version_number")
                vers_str = "%03d" % version if version is not None else "N/A"

                msg += __make_table_row("Version", "%s" % vers_str)

                if sg_item.get("entity"):
                    display_name = shotgun_globals.get_type_display_name(
                        sg_item.get("entity").get("type")
                    )
                    entity_str = "<b>%s</b> %s" % (
                        display_name,
                        sg_item.get("entity").get("name"),
                    )
                    msg += __make_table_row("Link", entity_str)

                # sort out the task label
                if sg_item.get("task"):

                    if sg_item.get("task.Task.content") is None:
                        task_name_str = "Unnamed"
                    else:
                        task_name_str = sg_item.get("task.Task.content")

                    if sg_item.get("task.Task.sg_status_list") is None:
                        task_status_str = "No Status"
                    else:
                        task_status_code = sg_item.get("task.Task.sg_status_list")
                        task_status_str = self._status_model.get_long_name(
                            task_status_code
                        )

                    msg += __make_table_row(
                        "Task", "%s (%s)" % (task_name_str, task_status_str)
                    )

                # if there is a version associated, get the status for this
                if sg_item.get("version.Version.sg_status_list"):
                    task_status_code = sg_item.get("version.Version.sg_status_list")
                    task_status_str = self._status_model.get_long_name(task_status_code)
                    msg += __make_table_row("Review", task_status_str)

                self.details_header.setText("<table>%s</table>" % msg)

                # tell details pane to load stuff
                sg_data = self._sg_data[key]
                # self.log('******************************************** sg_data')
                #for k, v in sg_data.items():
                #    self.log('{}: {}'.format(k, v))
                self._publish_history_model.load_data(sg_data)

            self.details_header.updateGeometry()

    def on_item_clicked(self, item, col):
        """
        Single click on tree item
        """
        #tree_item = self._asset_tree.itemAt(it, col)
        self.fw.log_info("Click on Tree item, {}".format(item.text(col)))
        key = item.text(col)
        key = os.path.basename(key)
        self.fw.log_info("Key is {}".format(key))
        self._key = key
        self._setup_details_panel(key)

    def _on_history_selection(self, selected, deselected):
        """
        Called when the selection changes in the history view in the details panel

        :param selected:    Items that have been selected
        :param deselected:  Items that have been deselected
        """
        # emit the selection_changed signal
        self.selection_changed.emit()

    def _on_detail_version_playback(self):
        """
        Callback when someone clicks the version playback button
        """
        # the code that sets up the version button also populates
        # a member variable which olds the current media center url.
        if self._current_version_detail_playback_url:
            QtGui.QDesktopServices.openUrl(
                QtCore.QUrl(self._current_version_detail_playback_url)
            )

    def _on_history_double_clicked(self, model_index):
        """
        When someone double clicks on a publish in the history view, run the
        default action

        :param model_index:    The model index of the item that was double clicked
        """
        # the incoming model index is an index into our proxy model
        # before continuing, translate it to an index into the
        # underlying model
        proxy_model = model_index.model()
        source_index = proxy_model.mapToSource(model_index)

        # now we have arrived at our model derived from StandardItemModel
        # so let's retrieve the standarditem object associated with the index
        item = source_index.model().itemFromIndex(source_index)

        # Run default action.
        sg_item = shotgun_model.get_sg_data(model_index)
        default_action = self._action_manager.get_default_action_for_publish(
            sg_item, self._action_manager.UI_AREA_HISTORY
        )
        if default_action:
            default_action.trigger()

    def open_context_menu(self, point):
        # Infos about the node selected.
        try:
            os_filebrowser_map = {
                "win32" : "Explorer",
                #"win32": "Chrome",
                "darwin" : "Finder"
            }
            os_filebrowser = "file browser"
            if sys.platform in os_filebrowser_map.keys():
                os_filebrowser = os_filebrowser_map[sys.platform]
            
            tree_item = self._asset_tree.itemAt(point)
            path_to_open = os.path.dirname(tree_item.data(3, QtCore.Qt.UserRole))
            self.fw.log_info("Right click on Tree item, data: {}".format(tree_item.data))

            menu = QtGui.QMenu()
            action = menu.addAction("Open path in {}".format(os_filebrowser),
                                    partial(open_browser, path_to_open))
                
            menu.exec_(self._asset_tree.mapToGlobal(point))

        except Exception as e:
            self.log_error(e)




    def save_ui_state(self, state_str=None):
        """
        Sync UI state and prefs locally to use for persistent UI features
        """
        self.fw.log_info("Saving state for UI: {}".format(state_str))
        try:
            data = self.prefs.read()
            data["hide_syncd"] = self._hide_syncd.isChecked()
            data['window_size'] = [self.width(), self.height()]
            data["force_sync"] = self._force_sync.isChecked()

            # save step filters~
            for f in self.use_filters:
                f = f.lower()
                filter_name = "{}_filters".format(f)
                filter_data = {}

                # use existing filter data if exists
                if data.get(filter_name):
                    filter_data = data.get(filter_name)
                # overwrite it with  our scan of presently checked items
                if hasattr(self, "_{}_actions".format(f)):
                    actions = getattr(self, "_{}_actions".format(f))
                    if actions:
                        for k,v in actions.items():
                            filter_data[k] = v.isChecked()

                data[filter_name] = filter_data
            
                self.prefs.write(data)
        except Exception as e:
            self.log_error(e)

    def filter_syncd_items(self):
        """
        Filter top-level items if theyre already sync'd
        """
        try:
            
            hide_syncd_checkstate = self._hide_syncd.isChecked()
            hid = 0
            for asset_name, asset_dict in self._asset_items.items():
                #logger.info(">>>>>>  asset_name: {}", asset_name)
                #logger.info(">>>>>>  asset_dict: {}", asset_dict)
                asset_status = asset_dict.get('status')
                if asset_status == "Syncd":

                    tree_item = asset_dict.get("tree_widget")
                    tree_item.setHidden(hide_syncd_checkstate)
                    if hide_syncd_checkstate is True:
                        hid += 1
            checkbox_text = "Hide if nothing to sync"
            if hid:
                checkbox_text += " ({} hidden)".format(hid)
            self._hide_syncd.setText(checkbox_text)

            
                
        except Exception as e:
            self.log_error(e)

    
    def filter_items(self):
        """
        Filter sync items away based on the step check-boxes
        """
        try:
            self._filtered_away = {}
            self._filtered_away['paths'] = []
            self.prefs.read()

            for f in self.use_filters:
                f = f.lower()
                self._filtered_away[f] = []
                filters = self.prefs.data.get('{}_filters'.format(f))

                for asset_name, asset_dict in self._asset_items.items():

                    if asset_dict.get('status') != "Syncd":
                    
                        for sync_path, sync_widget in asset_dict['child_widgets'].items():

                            if sync_path not in self._filtered_away['paths']:
                                filter_term = asset_dict['child_{}s'.format(f)].get(sync_path)
                                if filter_term:

                                    if filter_term in filters.keys():
                

                                        #self.fw.log_info("setting sync widget {} to {} : {}".format(sync_path, (not filters.get(filter_term)), filter_term))
                                        sync_widget.setHidden(not filters.get(filter_term))

                                        # keep track for user of what isnt being shown to them
                                        if (not filters.get(filter_term)) is True:
                                            self._filtered_away[f].append(sync_path)
                                            self._filtered_away['paths'].append(sync_path)

                        self.update_sync_counter(asset_name) 

                # indicate to user that items being filtered from view
                if len(self._filtered_away[f]) > 0:
                    getattr(self, "_{}_filter".format(f)).setIcon(self.make_icon("filter"))
                else:
                    getattr(self, "_{}_filter".format(f)).setIcon(QtGui.QIcon())     

        except Exception as e:
            self.log_error(e)

    def set_ui_interactive(self, state):
        """
        Common utility to lock the UI while info-gathering or syncing is occuring
        """
        # toggle the installed filters
        for f in self.use_filters:
            f = f.lower()
            getattr(self, "_{}_filter".format(f)).setEnabled(state)

        self._hide_syncd.setEnabled(state)
        self._do.setEnabled(state)  
        self._force_sync.setEnabled(state)

    def update_sync_counter(self, asset_name):
        """
        Update the top-level count of how many items there are to sync for an asset upon filters being applied
        """
        asset_dict = self._asset_items.get(asset_name)
        tree_widget = asset_dict.get("tree_widget")
        unfiltered_sync_count = len(asset_dict.get('child_widgets').keys())
        items_to_sync = [i for i,w in asset_dict.get('child_widgets').items() if not w.isHidden()]

        count_to_sync = len(items_to_sync)

        parent_asset_status = "{} to sync"
        plurality = ""

        filtered = unfiltered_sync_count-count_to_sync

        status = parent_asset_status.format(count_to_sync)
        if count_to_sync > 0:
            # set asset parent's status regarding count-left-to-sync
            tree_widget.setText(1, status)
            tree_widget.setIcon(1, self.make_icon('load'))
        if filtered:
            tree_widget.setText(1, "{} ({} filtered)".format(status, filtered))
            tree_widget.setIcon(1, self.make_icon('validate'))


    def update_available_filters(self, filter_info):
        """
        Populate the steps filter menu as steps are discovered in the p4 scan search
        """
        try:
            filter_type = filter_info[0]
            filter_value = filter_info[1]


            actions = getattr(self, "_{}_actions".format(filter_type))
            #if actions:
            if filter_value not in actions.keys():
                action = QtGui.QAction(self)
                
                action.setCheckable(True)

                self.prefs.read()
                filters = self.prefs.data.get('{}_filters'.format(filter_type))
                check_state = True
                if filter_value in filters.keys():
                    check_state = filters[filter_value]
                

                action.setChecked(check_state)
                action.setText(str(filter_value))
                action.triggered.connect(self.save_ui_state)
                action.triggered.connect(self.filter_items)

                getattr(self, "_{}_menu".format(filter_type)).addAction(action)
                actions[filter_value] = action

        except Exception as e:
            self.log_error(e)

    
    def make_top_level_tree_item(self, asset_name=None, status=None, version=None, details=None, icon=None, root_path=None):
        """
        Creates QTreeWidgetItem to display asset information
        """
        tree_item = QtGui.QTreeWidgetItem(self._asset_tree)

        # if user has chosen to not see these 
        if self._hide_syncd.isChecked() and status == "Syncd":
            tree_item.setHidden(True)

        tree_item.setText(self.ASSET_NAME, asset_name)
        tree_item.setText(self.STATUS, status)
        tree_item.setText(self.VERSION, version)
        tree_item.setText(self.DETAIL, details)
        tree_item.setIcon(self.STATUS, self.make_icon(icon))

        if root_path:
            tree_item.setData(2, QtCore.Qt.UserRole, root_path)

        self._asset_tree.addTopLevelItem(tree_item)

        
        return tree_item


    def make_sync_tree_item(self, sync_item_info):
        """
        Creates child QTreeWidgetItem under asset item to display filename and status of the sync
        """
        #self.fw.log_info('trying to make child item for {}'.format(sync_item_info))
        try:
            asset_name = sync_item_info.get("asset_name")
            item_found = sync_item_info.get("item_found")
            status = sync_item_info.get('status')
            step = sync_item_info.get('step')
            file_type = sync_item_info.get('type')
            version = sync_item_info.get('version')

            # self.fw.log_info(version)
            tree_item = self._asset_items[asset_name].get("tree_widget")

            child_tree_item = QtGui.QTreeWidgetItem(tree_item)

            asset_file_path = item_found.get('clientFile') 
            asset_file_name = os.path.basename(item_found.get('clientFile'))


            filtered = None

            for f in self.use_filters:
                f = f.lower()
                if sync_item_info.get(f):
                    filter_term = sync_item_info.get(f)
                    filters = self.prefs.data.get('{}_filters'.format(f))
                    if filter_term in filters.keys():
                        if not filtered:
                            child_tree_item.setHidden(not filters.get(filter_term))
                            filtered = True
                            self.update_sync_counter(asset_name)
                    child_filter_term = self._asset_items[asset_name].get("child_{}s".format(f))  
                    child_filter_term[asset_file_path] = filter_term


            child_tree_item.setText(self.ASSET_NAME, asset_file_name) #If it is not clientFile specifically it seems like the name is within that info at least the correct wording is probably in clientFile
            child_tree_item.setText(self.STATUS, status.title())
            child_tree_item.setText(self.VERSION, str(version))
            child_tree_item.setText(self.DETAIL, asset_file_path) #after testing it works as intended but we need to link it to the actual names the correct wording is probably in depotFile
            child_tree_item.setIcon(self.STATUS, self.make_icon("load"))
            child_tree_item.setData(2, QtCore.Qt.UserRole, asset_file_path)



            child_tree_item.status = status
            
            child_widgets = self._asset_items[asset_name].get("child_widgets")
            child_widgets[ asset_file_path ] = child_tree_item

            #self.filter_items
            
        except Exception as e:
            self.log_error(e)
        

    def asset_info_handler(self, info_processed_dict):
        """
        Main handler for asset information. 
        """
        name = info_processed_dict.get("asset_name")
        if name not in  self._asset_items.keys():

            tree_widget = self.make_top_level_tree_item(asset_name=info_processed_dict.get("asset_name"),
                                        status= info_processed_dict.get("status"),
                                        version=info_processed_dict.get("version"),
                                        details= info_processed_dict.get("details"),
                                        icon = info_processed_dict.get("icon"),
                                        root_path = info_processed_dict.get("root_path")                         
            )
            
            asset_UI_mapping = {}
            asset_UI_mapping['tree_widget']= tree_widget
            asset_UI_mapping['asset_info']= info_processed_dict.get("asset_item")
            asset_UI_mapping['status'] = info_processed_dict.get("status")
            asset_UI_mapping['child_widgets'] = {}

            for f in self.use_filters:
                asset_UI_mapping['child_{}s'.format(f.lower())] = {}

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


            self.filter_items()
            self.filter_syncd_items()


    def populate_assets(self):
        """
        Iterate through tk-multi-perforce delivered list of asset information, 
        Utilize a global threadpool to process workers to ask P4 server for what 
        there is to sync for these. 
        """
        try:
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

                if self._force_sync.isChecked():
                    asset_info_gather_worker.force_sync = True

                asset_info_gather_worker.info_gathered.connect( self.asset_info_handler )
                asset_info_gather_worker.progress.connect( self.iterate_progress )
                asset_info_gather_worker.item_found_to_sync.connect(self.make_sync_tree_item)
                asset_info_gather_worker.status_update.connect(self.set_progress_message)
                asset_info_gather_worker.includes.connect(self.update_available_filters)

                # if hasattr(self, 'child_asset_ids'):
                #     if self.child_asset_ids:
                #         if entity_to_sync.get('id') in self.child_asset_ids:
                #             asset_info_gather_worker.child = True
                self._sg_data = asset_info_gather_worker.run()
                # self.threadpool.start(asset_info_gather_worker)
        except Exception as e:
            self.log_error(e)


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
        try:
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
            # self.threadpool = QtCore.QThreadPool.globalInstance()
            # self.threadpool.setMaxThreadCount(min(24, self.threadpool.maxThreadCount()))

            # self.fw.log_debug("Starting Threaded P4 Sync...")

            # setup workers for multiprocessing

            for sync_worker in workers:
                sync_worker.run()
        except Exception as e:
            self.log_error(e)


    def log(self, msg, error=0):
        if logger:
            if error:
                logger.warn(msg)
            else:
                logger.info(msg)

        print(msg)
