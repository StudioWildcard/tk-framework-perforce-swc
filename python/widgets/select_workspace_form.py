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
import subprocess
import os
import collections
import glob

logger = sgtk.platform.get_logger(__name__)

from .ui.select_workspace_form import Ui_SelectWorkspaceForm
    
class SelectWorkspaceForm(QtGui.QWidget):
    """
    """
    
    @property
    def exit_code(self):
        return self._exit_code
    
    @property
    def hide_tk_title_bar(self):
        return True    
    
    def __init__(self, server, user, workspace_details, current_workspace=None, parent=None):
        """
        Construction
        """
        QtGui.QWidget.__init__(self, parent)

        QtCore.QCoreApplication.processEvents()
        # setup UI:
        self.__ui = Ui_SelectWorkspaceForm()
        self.__ui.setupUi(self)
        
        self.__ui.details_label.setText("Perforce Workspace for user '%s' on server '%s'"
                                        % (user, server))
        
        self.__ui.cancel_btn.clicked.connect(self._on_cancel)
        self.__ui.ok_btn.clicked.connect(self._on_ok)

        self.__ui.folderBtn.clicked.connect(self._selectDirDialog)
        self.__ui.workspace_list.clicked.connect(self._on_workspace_clicked)
        self.__ui.workspace_list.doubleClicked.connect(self._on_workspace_doubleclicked)
        self.__ui.workspace_list.currentCellChanged.connect(self._on_workspace_changed)
        self.__ui.workspace_list.installEventFilter(self)

        self._fw = sgtk.platform.current_bundle()

        self._workspace_details = workspace_details

        self._root_path = None
        self.get_root_path()

        self._current_workspace = current_workspace

        self._mapping_status = self._get_drive_status()
        self._startup_folder = "{}/Microsoft/Windows/Start Menu/Programs/Startup".format(os.getenv('APPDATA'))
        # init list:

        # self._initialize(workspace_details, current_workspace)

        
        # update UI:
        self._update_ui()

    @property
    def workspace_name(self):
        """
        Return the name of the currently selected workspace: 
        """
        items = self.__ui.workspace_list.selectedItems()
        if not items:
            return None
        selected_row = items[0].row()
        
        item = self.__ui.workspace_list.item(selected_row, 0)
        return item.text()

    def get_root_path(self):
        if self._workspace_details and len(self._workspace_details) > 0:
            self._root_path = os.path.abspath(
                    os.path.join(self._fw.sgtk.roots.get('primary'), os.pardir))  # one directory above project root
            logger.debug("root path: {}".format(self._root_path))

    def eventFilter(self, q_object, event):
        """
        Custom event filter to filter enter-key press events from the workspace
        list control
        """
        if q_object == self.__ui.workspace_list and event.type() == QtCore.QEvent.KeyPress:
            # handle key-press event in the workspace list control:
            if event.key() == QtCore.Qt.Key_Return and self.__ui.workspace_list.selectedItems():
                # same as pressing ok:
                self._on_ok()
                return True
                
        # let default handler handle the event:
        return QtCore.QObject.eventFilter(self, q_object, event)

    def _selectDirDialog(self):

        self._mapping_status = self._get_drive_status()
        selectedDir = QtGui.QFileDialog.getExistingDirectory(
            self,
            "Select an empty folder to create project drive mapping",
            self._root_path,
            QtGui.QFileDialog.ShowDirsOnly
            )
        # self.__ui.folderInput.setText(selectedDir)
        drive = self._root_path[0:2]
        drive = drive.lower()

        if os.path.isdir(selectedDir):

            if not os.listdir(selectedDir):
                self.log_status("Selected folder {} is empty".format(selectedDir))
                if self._root_path and len(self._root_path) >= 2:
                    self._create_drive_mapping(drive, selectedDir)
                    self.__ui.folderInput.setText(selectedDir)
                else:
                    self.log_status("Error with project root path: {}".format(self._root_path))
            else:
                self.log_status("\nSelected folder {} is not empty".format(selectedDir))
                result = self._warning_dialog()
                if result:
                    self._create_drive_mapping(drive, selectedDir)
                    self.__ui.folderInput.setText(selectedDir)
        else:
            self.log_status("Selected folder {} does not exist, please select another folder".format(selectedDir))
        return selectedDir

    def _warning_dialog(self):
        display_msg = "Warning: The selected folder is not empty. This could create problems syncing files from Perforce."
        confirmation_box = QtGui.QMessageBox()
        confirmation_box.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint)
        confirmation_box.setText(display_msg)
        confirmation_box.setWindowTitle("Warning!")
        confirmation_box.setStandardButtons(
            QtGui.QMessageBox.Yes | QtGui.QMessageBox.No)
        yes_btn = confirmation_box.button(QtGui.QMessageBox.Yes).setText("Proceed Anyway")
        no_btn = confirmation_box.button(QtGui.QMessageBox.No).setText("Cancel")
        result = confirmation_box.exec_()
        if result == QtGui.QMessageBox.Yes:
            return True
        elif result == QtGui.QMessageBox.No:
            return False

    def _on_cancel(self):
        """
        """
        self._exit_code = QtGui.QDialog.Rejected
        self.close()
        
    def _on_ok(self):
        """
        """
        self._exit_code = QtGui.QDialog.Accepted
        self.close()
    
    def _on_workspace_doubleclicked(self, index):
        """
        """
        if self.__ui.workspace_list.selectedItems():
            self._on_ok()

    def _on_workspace_clicked(self, index):
        """
        """
        self._update_ui()
    
    def _on_workspace_changed(self):
        """
        """
        self._update_ui()
        
    def _update_ui(self):
        """
        Update UI
        """
        something_selected = bool(self.__ui.workspace_list.selectedItems())
        self.__ui.ok_btn.setEnabled(something_selected)


    def _display_workspace(self):
        """
        """
        column_labels = ["Workspace", "Description", "Location"]
        self.__ui.workspace_list.setColumnCount(len(column_labels))
        self.__ui.workspace_list.setHorizontalHeaderLabels(column_labels)
        
        self.__ui.workspace_list.setRowCount(len(self._workspace_details))
        
        selected_index = -1
        for wsi, ws in enumerate(self._workspace_details):
            ws_name = ws.get("client", "").strip()
            if ws_name == self._current_workspace:
                selected_index = wsi

            self.__ui.workspace_list.setItem(wsi, 0, QtGui.QTableWidgetItem(ws_name))
            self.__ui.workspace_list.setItem(wsi, 1, QtGui.QTableWidgetItem(ws.get("Description", "").strip()))
            #self.__ui.workspace_list.setItem(wsi, 2, QtGui.QTableWidgetItem(ws.get("Root", "").strip()))
            self.__ui.workspace_list.setItem(wsi, 2, QtGui.QTableWidgetItem(self._root_path))

        if selected_index >= 0:
            self.__ui.workspace_list.selectRow(selected_index)
            self.log_status("\nWorkspace {} is selected, click OK to confirm".format(self._current_workspace))
        else:
            self.__ui.workspace_list.clearSelection()


        self.__ui.workspace_list.setSortingEnabled(True)
        self.__ui.workspace_list.resizeColumnToContents(0)
        QtCore.QCoreApplication.processEvents()

    def _get_drive_status(self):
        # check the project drive
        self.log_status('Checking project drive mapping ...')
        result, drive, path = self._check_project_drive()
        if result:
            msg = '\nDrive {} is mapped'.format(drive)
            self.log_status(msg)
            self.__ui.folderInput.setText(path)
            self.__ui.folderBtn.setText("Change mapping folder")
            # self._set_workspace()
            self._display_workspace()
            return True
        else:
            msg = '\nSelect a folder to create project drive mapping '
            self.log_status(msg)
            return False
        return False


    def _check_project_drive(self):
        """
        Check if project drive mapping exists
        """
        self.log_status('root_path: {}'.format(self._root_path))

        available_drives = self.get_available_drives()
        for drive, path in available_drives.items():
            drive = drive.strip()
            if self._root_path == drive:
                self.log_status('Drive exists: {}'.format(drive))
                return True, drive, path
        self.log_status("Drive does not exist")
        return False, None, None

    def _create_drive_mapping(self, drive, folder):
        """
        Create a drive mapping on local machine using 'subst' command
        """

        # Remove drive mapping if necessary
        self.log_status("\nRemoving existing mapping of drive {} if needed ...".format(drive))
        #if not self._mapping_status:
        try:
            map_cmd = "subst {} /d".format(drive, folder)
            pipe = subprocess.Popen(map_cmd, shell=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            output, error = pipe.communicate()
            result = pipe.returncode
            if result == 0:
                self.log_status("\nMapping of drive {} is removed".format(drive))

        except:
            pass

        try:
            self.log_status("\nCleaning all files at startup folder from occurrences of old mapped drive {} ...".format(drive))
            self._clean_startup_files(drive)
        except:
            pass

        self.log_status("\nMapping drive {} to folder {} ...".format(drive, folder))
        map_cmd = "subst {} {}".format(drive, folder)
        pipe = subprocess.Popen(map_cmd, shell=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, error = pipe.communicate()
        result = pipe.returncode
        if result == 0:
            self.log_status("Successfully mapped drive {} to folder {}".format(drive, folder))
            self.__ui.folderInput.setText(folder)
            self.__ui.folderBtn.setText("Change mapping folder")
            self.log_status("Displaying workspace {} ...".format(self._current_workspace))
            self._create_startup_file(drive, folder)
            # self._set_workspace()
            self._display_workspace()

    def _set_workspace(self):
        self._display_workspace()
        self.log_status("\nSelect the workspace {} and click OK to confirm".format(self._current_workspace))
        self.log_status("Or double click on the workspace {}".format(self._current_workspace))

    def _clean_startup_files(self, drive):
        """
        Clean all files at startup folder from occurrences of old mapped drive
        """
        file_match = '{}'.format(self._startup_folder)
        file_list = glob.glob('%s/*.bat' % file_match)
        for path in file_list:
            self.log_status("Cleaning file {}".format(path))
            os.chmod(path, 0o0777)
            self._clean_file(path, drive)

    def _clean_file (self, file_name, drive):
        """
        Clean one file at startup folder from occurrences of old mapped drive
        """
        with open(file_name, "r") as f:
            lines = f.readlines()
        with open(file_name, "w") as f:
            for line in lines:
                if drive not in line.strip("\n"):
                    f.write(line)
        f.close()

    def _create_startup_file(self, drive, folder):
        """
        Create a .bat file to do the drive mapping at startup
        """
        file_name = "SGDriveMapping.bat"
        file_path = "{}/{}".format(self._startup_folder,file_name)

        drive = drive.lower()
        f = open(file_path, "a")
        f.write("subst {} {}\n".format(drive, folder))
        f.close()

        #os.chmod(file_path, 509)
        os.chmod(file_path, 0o777)
        if os.path.exists(file_path):
            self.log_status("\nUpdated {} file at startup folder {}".format(file_name, self._startup_folder))
            return file_path
        return None


    def get_available_drives(self):
        """
        Get user workspaces on local machine using 'subst' command
        """
        output_path = self.get_output_path()
        cmd = "subst > {}".format(output_path)
        result = subprocess.Popen(cmd, shell=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, error = result.communicate()

        available_drives = collections.OrderedDict()
        # try:
        with open(output_path, 'r') as in_file:
            lines = in_file.readlines()
            for line in lines:
                line = line.rstrip()
                line = line.split(": => ")
                if len(line) == 2:
                    root, path = line[0], line[1]
                    available_drives[root] = path

        in_file.close()

        # except:
        #    self.log('Unable to read mapping file: {}'.format(output_path))
        #    pass
        # self.log('workspaces_list: {}'.format(workspaces_list))
        return available_drives

    def get_output_path(self):
        output_folder = "C:/temp"
        self.create_folder(output_folder)
        output_path = "{}/mapping_output.txt".format(output_folder)
        return output_path

    def create_folder(self, folder_name):
        """
        create output directory if it doesn't exit
        :param folder_name:
        :return:
        """
        if not os.path.exists(folder_name):
            # handle race condition (multiple tasks on same machine) of two tasks trying create at same time
            try:
                os.makedirs(folder_name)
            except Exception as ex:
                if 'file already exists' in str(ex):
                    # just continue as folder already created by other concurrent task on same machine
                    pass
                else:
                    # another error that likely will need to be investigated
                    raise

    def log(self, msg, error=0):
        if logger:
            if error:
                logger.warn(msg)
            else:
                logger.info(msg)
        print(msg)

    def add_status(self, status):
        self.__ui.status_dialog.append(status)
        QtCore.QCoreApplication.processEvents()

    def log_status(self, status):
        self.add_status(status)
        self.log(status)



    
    
    
    
    
    
    