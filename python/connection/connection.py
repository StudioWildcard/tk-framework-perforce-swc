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
import hashlib
import subprocess

import sgtk
from sgtk import TankError
from sgtk.platform.qt import QtGui

from P4 import P4, P4Exception

from .user_settings import UserSettings
from ..util.progress import ProgressHandler

logger = sgtk.platform.get_logger(__name__)

class SgtkP4Error(TankError):
    """
    Specialisation of TankError raised after catching and processing a P4Exception
    """
class SgtkP4TCPConnectionError(TankError):
    """
    Specialisation of TankError raised after catching and processing a P4Exception that deals with no TCP connections
    """

# global connection rlock to ensure that attempting to connect to Perforce happens exclusively.  This
# stops the user from being presented with multiple password entry dialogs if the framework needs to
# connect from multiple threads and they enter the correct password for the first thread.
_g_connection_lock = threading.RLock()


class ConnectionHandler(object):
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
        self.templates = {"swc-perforce.studiowildcard.com:1666":"sgtk_Ark2Depot_master",
                          "ssl:192.168.2.238:1666":"sgtk_devaDepot_master",
                          "ssl:artifact.studiowildcard.com:20654":"sgtk_devaDepot_master"}

    @property
    def connection(self):
        """
        Returns the P4 object for this connection.

        :returns: A P4.P4 object.
        """
        return self._p4

    def disconnect(self):
        """
        Disconnect the current p4 connection if there is one
        """
        if self._p4 and self._p4.connected():
            self._p4.disconnect()
            self._fw.log_debug("Disconnected from perforce server.")
        self._p4 = None

    def connect_to_server(self):
        """
        Open a connection to the specified server.
        Returns a new P4 connection object if successful
        """

        server = self.p4_server
        host = self._fw.get_setting("host")

        # create new P4 instance
        p4 = P4()

        # set exception level so we only get exceptions for
        # errors, not warnings
        p4.exception_level = 1

        # load the server configuration:
        p4.port = str(server)
        if host:
            p4.host = str(host)

        # attempt to connect to the server:
        try:
            self._fw.log_debug("Attempting to connect to %s" % server)
            # connect to the p4 server
            p4.connect()
            if p4.connected():
                self._fw.log_debug("Connected!!!")
        except Exception as e:
            # Oh no, we failed to connect!
            self._fw.log_debug("Failed to connect!")
            msg = None
            if p4.errors:
                msg = p4.errors[0]
            else:
                # TCP connect failure rather unhelpfully just raises an exception
                # and doesn't add the error to p4.errors! So lets parse the exception
                # to get some useful information.
                msg = str(e)
                mo = re.match("\[P4\..*\(\)\] ", msg)
                if mo:
                    msg = msg[mo.end():]

            raise SgtkP4TCPConnectionError(msg)

        self._p4 = p4
        return self._p4

    def _ensure_connection_is_trusted(self, allow_ui=True, parent_widget=None):
        """
        Ensure that the current connection is trusted and if not then prompt the user if possible.  For all
        non-ssl connections, this always returns True

        :param allow_ui:        True if we are allowed to prompt the user via a UI.
        :param parent_widget:   The widget any UI should be parented to
        :returns:               True if the connection is trusted, otherwise False.
        :raises:                A TankError or SgtkP4Error if something goes wrong.
        """
        #if not self._p4.port.startswith("ssl:"):
            # non-ssl servers are always trusted
        return (True, False)

        fingerprint = None
        fingerprint_changed = False
        try:
            # run trust command to query the current trust.  This returns either something like the
            # following if trust is not already established:
            #
            # ["The fingerprint of the server of your P4PORT setting\n'ssl:192.168.0.21:1668'
            #   (192.168.0.21:1668) is not known.\nThat fingerprint is
            #   F2:77:7B:7C:A4:B4:F2:7A:ED:C4:73:04:4D:B4:68:BD:D1:52:8F:44"]
            #
            # If trust is established then it returns:
            #
            # ["Trust already established.\n"]
            #
            # Wouldn't it be nice if there was a simple query command instead of having to parse the
            # returned message!
            p4_res = self._p4.run_trust()
        except P4Exception as e:
            # if for some reason the client has an ssl fingerprint but it doesn't match the servers then we get
            # an exception, something like this:
            #
            # ["******* WARNING P4PORT IDENTIFICATION HAS CHANGED! *******\nIt is possible that someone
            #   is intercepting your connection\nto the Perforce P4PORT '192.168.0.21:1668'\nIf this is
            #   not a scheduled key change, then you should contact\nyour Perforce administrator.\nThe
            #   fingerprint for the mismatched key sent to your client is\n
            #   F2:77:7B:7C:A4:B4:F2:7A:ED:C4:73:04:4D:B4:68:BD:D1:52:8F:44"]
            #
            # We should probably tell the user about this!
            error_msg = self._p4.errors[0] if self._p4.errors else ""
            if error_msg.startswith("******* WARNING P4PORT IDENTIFICATION HAS CHANGED! *******"):
                reg_exp = re.compile(".*The fingerprint for the mismatched key sent to your client is\\n"
                                     "(?P<fingerprint>([A-F0-9]{2}:)+[A-F0-9]{2})", re.DOTALL)
                re_res = reg_exp.match(error_msg)
                if re_res:
                    fingerprint = re_res.group("fingerprint")

            if not fingerprint or not (allow_ui and self._fw.engine.has_ui):
                # this is serious and we can't ask the user for verification so lets raise
                raise SgtkP4Error(self._p4.errors[0] if self._p4.errors else str(e))

            fingerprint_changed = True
        else:
            if not p4_res:
                raise TankError("p4 trust returned an unexpected result: %s" % p4_res)
            msg = p4_res[0]
            if msg.startswith("Trust already established."):
                # awesome!
                return (True, False)

            # trust isn't established and we can only attempt to establish trust if we have ui:
            if not (allow_ui and self._fw.engine.has_ui):
                raise TankError(msg)

            # connection isn't trusted yet - extract the fingerprint from the command result:
            reg_exp = re.compile(".*That fingerprint is (?P<fingerprint>([A-F0-9]{2}:)+[A-F0-9]{2})", re.DOTALL)
            re_res = reg_exp.match(msg)
            """
            if not re_res:
                # unexpected message - lets hope this never happens!
                raise TankError("Failed to determine ssl fingerprint from '%s'!" % msg)
            """
            if re_res:
                fingerprint = re_res.group("fingerprint")

        """
        if not fingerprint:
            raise TankError("Failed to determine ssl fingerprint to use!")
        """
        # we have a fingerprint, lets ask the user if it should be trusted:
        establish_trust, show_details = self._fw.engine.execute_in_main_thread(self._prompt_for_trust,
                                                                               fingerprint,
                                                                               fingerprint_changed,
                                                                               parent_widget)
        if not establish_trust:
            return (False, show_details)

        # ok, so lets attempt to establish some trust (if only all trust in life was this simple...):
        try:
            try:
                # install the fingerprint that the server sent over:
                self._p4.run_trust("-i", fingerprint)
            except P4Exception:
                # note that changing the fingerprint will always raise a P4Exception if there was previously
                # a fingerprint that has now changed!
                if not fingerprint_changed:
                    # something else must have gone wrong!
                    raise

            # check that trust has been established:
            p4_res = self._p4.run_trust()
            if not p4_res:
                raise TankError("p4 trust returned an unexpected result: %s" % p4_res)
            if not p4_res[0].startswith("Trust already established."):
                # boo!
                raise TankError("Failed to establish trust with server!")

        except P4Exception as e:
            raise SgtkP4Error(self._p4.errors[0] if self._p4.errors else str(e))

        # all good!
        return (True, False)

    def _prompt_for_trust(self, fingerprint, fingerprint_changed, parent_widget):
        """
        Prompt the user to see if they trust this connection.  Runs in the main thread.

        :param fingerprint:          The fingerprint returned for the server
        :param fingerprint_changed:  True if the fingerprint is different to a previously trusted
                                     fingerprint - may indicate communication has been intercepted
        :param parent_widget:        The widget the dialog should be parented to
        :returns:                    (Bool, Bool) tuple containing (is_trusted, show_details) indicating if
                                     the user trusts the connection/fingerprint and if the details dialog
                                     should be shown.
        """
        # show the trust dialog:
        from ..widgets import TrustForm
        res, widget = self._fw.engine.show_modal("Perforce Fingerprint Required", self._fw, TrustForm,
                                                 self._p4.port, fingerprint, fingerprint_changed,
                                                 (parent_widget is None), parent_widget)
        if res == TrustForm.SHOW_DETAILS:
            # just return the result:
            return (False, True)
        elif res != QtGui.QDialog.Accepted:
            # user hit cancel
            return (False, False)
        else:
            # user hit ok
            return (True, False)

    def _login_user(self, user, parent_widget=None):
        """
        Log-in the specified Perforce user if required.
        """
        if not self._p4 or not self._p4.connected():
            raise TankError("Unable to log user in without an open Perforce connection!")

        self._p4.user = str(user)

        login_req = self._login_required_user()
        self.log('Login required is: {} '.format(login_req))

        if login_req:
            self.log('login required?: {} '.format(login_req))
            logged_in, _ = self._do_login(True, parent_widget)
            self.log('logged_in?: {} '.format(logged_in))
            if not logged_in:
                raise TankError("Unable to login user %s without a password!" % user)


    def _prompt_for_workspace(self, user, initial_ws, parent_widget=None):
        """
        Prompt the user to enter/select the client/workspace to use

        :returns: String - the workspace to use for the connection
        """
        if not self._p4 or not self._p4.connected():
            raise TankError("Unable to retrieve list of workspaces without an open Perforce connection!")

        # get all avaliable workspaces for the current user and this host machine:
        all_workspaces = []
        try:
            all_workspaces = self._p4.run_clients("-u", user)
        except P4Exception as e:
            raise SgtkP4Error(self._p4.errors[0] if self._p4.errors else str(e))

        host = socket.gethostname()
        self._fw.log_debug("Current host '%s'" % host)
        self._fw.log_debug("All workspaces: %s" % all_workspaces)
        # Get all workspaces that are assigned for this user for this machine or
        # that are accessible from any machine. Note: Host is always set, but can
        # be an empty string. In that case, we will consider the host for that workspace
        # to be the current host.

        self._selected_workspaces = [ws for ws in all_workspaces if (ws.get("Host") or host) == host]

        workspace_name = self._sgtk_workspace()

        self._filtered_workspaces = [ws for ws in all_workspaces if ws.get("client").lower() == workspace_name.lower()]
        self.log('Filtered workspaces: {}'.format(self._filtered_workspaces))

        # show the password entry dialog:
        try:
            from ..widgets import SelectWorkspaceForm

            res, widget = self._fw.engine.show_modal("Perforce Workspace", self._fw, SelectWorkspaceForm,
                                                     self._p4.port, user,
                                                     self._filtered_workspaces, workspace_name, parent_widget)

            if res == QtGui.QDialog.Accepted:
                return widget.workspace_name

        except TankError:
            pass

        return None

    def connect(self, local_framework=False, allow_ui=True, user=None, password=None, workspace=None):
        """
        Utility method that returns a connection using the current configuration.  If a connection
        can't be established and the user is in ui mode then they will be prompted to edit the
        connection details.

        :param allow_ui:    If True and the engine can show UI then we can prompt the user through
                            dialogs if needed.  If False then UI is not allowed so this method will
                            just raise if it can't connect for some reason.
        :param user:        The username of the user to use when connecting with the Perforce server
        :param password:    The password for the specified user to use when connecting to the server
        :param workspace:   The name of the workspace/client-spec to use for this user when connecting
                            to the server
        :returns:           A new connected P4 instance if successful or None if the user cancels.
        :raises:            TankError if connecting failed for some reason other than the user cancelling.
        """
        self.log('Connecting to the server ...')
        server = self.p4_server
        if not user:
            sg_user = sgtk.util.get_current_user(self._fw.sgtk)
            user = self._fw.execute_hook("hook_get_perforce_user", sg_user=sg_user)
            if not user:
                raise TankError("Perforce: Failed to find Perforce user for Shotgun user '%s'"
                                % (sg_user if sg_user else "<unknown>"))

        # lock around attempting to connect so that only one thread will attempt
        # to connect at a time.
        global _g_connection_lock
        _g_connection_lock.acquire()
        try:
            # first, attempt to connect to the server:
            self.log('first, attempt to connect to the server ...')
            try:
                self.connect_to_server()
            except SgtkP4TCPConnectionError as e:
                raise 

            # then ensure that the connection is trusted:
            if local_framework:
                self.log('then ensure that the connection is trusted ...')
                try:
                    is_trusted, show_details = self._ensure_connection_is_trusted(allow_ui)
                    if show_details:
                        # switch to connection dialog - raise a TankError here which will get
                        # raised if we aren't able to show the connection details dialog
                        raise TankError("Perforce: Failed to establish trust with server!")
                    elif not is_trusted:
                        # user decided not to trust!:
                        return None
                except SgtkP4Error as e:
                    raise TankError("Perforce: Connection to server '%s' is not trusted: %s" % (server, e))

            # log-in user:
            self.log('then  log-in user ...')
            try:
                self._p4.user = user

                # if log-in is required then log-in:
                if not local_framework:
                    login_req = False
                else:
                    login_req = self._login_required_user()
                self.log('Login required?: {}'.format(login_req))
                if login_req:
                    if password:
                        self._p4.password = password

                    logged_in, show_details = self._do_login(allow_ui)
                    if show_details:
                        # switch to connection dialog - raise a TankError here which will get
                        # raised if we aren't able to show the connection details dialog
                        raise TankError("Perforce: Failed to login user '%s'!" % user)
                    elif not logged_in:
                        # user cancelled log-in!
                        return None
            except SgtkP4Error as e:
                raise TankError("Perforce: Failed to login user '%s' - %s" % (user, e))

            else:
                self.log('Login is successful')


            # finally, validate the workspace:
            self.log('finally, validate the workspace ...')
            workspace = workspace if workspace is not None else self._sgtk_workspace()
            if workspace:
                try:
                    self._validate_workspace(workspace, user)
                    #self.log('workspace after validation : {}'.format(workspace))
                    self._p4.client = str(workspace)
                except SgtkP4Error as e:
                    raise TankError("Perforce: Workspace '%s' is not valid! - %s" % (workspace, e))

            try:
                self._fw.log_metric("Connected")
            except:
                # ignore all errors. ex: using a core that doesn't support metrics
                pass

            return self._p4

        except TankError as e:
            # failed to connect to server - switch to UI mode
            # if available instead:
            if isinstance(e, SgtkP4TCPConnectionError):
                raise
            elif allow_ui and self._fw.engine.execute_in_main_thread(self.__has_ui):
                # just show the connection UI instead:
                return self.connect_with_dlg()
            else:
                # re-raise the last exception:
                raise
        finally:
            _g_connection_lock.release()

    def is_connected(self):
        """
        Returns p4
        """
        p4 = None
        if self._p4 and self._p4.connected():
            p4 = self._p4
        return p4

    def __has_ui(self):
        """
        Check if the engine has a ui
        """
        return self._fw.engine.has_ui

    def connect_with_dlg(self):
        """
        Present the connection dialog to the user and prompt them to connect in a thread-safe
        manner.

        :returns: A connected, logged-in p4 instance if successful.
        """
        global _g_connection_lock
        _g_connection_lock.acquire()
        try:
            # ensure this always runs on the main thread:
            return self._fw.engine.execute_in_main_thread(self._connect_with_dlg)
        finally:
            _g_connection_lock.release()

    def _connect_with_dlg(self):
        """
        Actual implementation of connect_with_dlg.

        :returns: A connected, logged-in p4 instance if successful.
        """
        server = self.p4_server
        sg_user = sgtk.util.get_current_user(self._fw.sgtk)
        user = self._fw.execute_hook("hook_get_perforce_user", sg_user=sg_user)

        # establish a connection
        self.connect(local_framework=True)

        #logged_in, show_details = self._do_login(allow_ui=True)
        try:
            self._fw.log_debug("Attempting to log-in user %s to server %s" % (self._p4.user, self._p4.port))
            self._p4.run_login()
        except P4Exception as e:
            # keep track of error message:
            error_msg = self._p4.errors[0] if self._p4.errors else str(e)
            self._fw.log_debug(error_msg)
        else:
            # successfully logged in!
            return (True, False)

        try:
            from ..widgets import OpenConnectionForm

            # get initial user & workspace from settings:
            initial_workspace = self._get_current_workspace()
            btn_txt = "Browse..."
            if initial_workspace:
                btn_txt = "Change..."

            # show the connection dialog:
            result, _ = self._fw.engine.show_modal("Perforce Connection", self._fw, OpenConnectionForm,
                                                   server, user, sg_user, initial_workspace, self._setup_connection_dlg, btn_txt)

            self.log('Connection result is : {}'.format(result))
            return result

        except Exception:
            pass

        return None

    def _setup_connection_dlg(self, widget):
        """
        Connects dialog events to the ConnectionHandler.
        """
        widget.browse_workspace_clicked.connect(self._on_browse_workspace)
        widget.open_clicked.connect(self._on_open_connection)

    def _do_login(self, allow_ui=True, parent_widget=None):
        """
        Login to the Perforce connection for the current user.  This first attempts to login and if it
        fails then it will prompt the user for their password until successful or the user cancels.

        :param allow_ui:        True if this method is allowed to show ui requesting the password from the
                                user.  If False then the method will attempt to connect one and return
        :param parent_widget:   The parent QWidget that the prompt dialog should be parented to.
        :returns:               Tuple (success, show_details) - success is True if the user successfully logged
                                in, False otherwise.  show_details will be true if the user clicked the 'Show
                                Details' button on the password prompt instead of entering their password.
        """
        error_msg = None
        is_first_attempt = True

        # loop until we successfully log in or decide to cancel:
        while True:

            # attempt to log-in:
            try:
                self._fw.log_debug("Attempting to log-in user %s to server %s" % (self._p4.user, self._p4.port))
                self._p4.run_login()
            except P4Exception as e:
                # keep track of error message:
                error_msg = self._p4.errors[0] if self._p4.errors else str(e)
                self._fw.log_debug(error_msg)
            else:
                # successfully logged in!
                return (True, False)

            if allow_ui and self._fw.engine.has_ui:
                self._fw.log_debug("Attempting to log-in user %s to server %s using Perforce Password form" % (self._p4.user, self._p4.port))
                self._fw.log_debug("Env variable P4PASSWD is: %s" % os.environ.get('P4PASSWD'))
                prompt_error_msg = None
                if not is_first_attempt:
                    prompt_error_msg = "Log-in failed: %s" % error_msg

                # prompt for a password in the main thread:
                from ..widgets import PasswordForm
                res, password = self._fw.engine.execute_in_main_thread(self._prompt_for_password,
                                                                       prompt_error_msg,
                                                                       parent_widget)

                if res == PasswordForm.SHOW_DETAILS:
                    # user hit the show-details button so return accordingly:
                    return (False, True)
                elif res != QtGui.QDialog.Accepted:
                    # User hit cancel!
                    return (False, False)

                # update password for next iteration:
                self._p4.password = password
                # Store password as MD5 hash
                self._store_password(password)
                is_first_attempt = False

            else:
                # no UI so just raise error:
                raise SgtkP4Error(error_msg)

    def _store_password(self, password):
        """
        Store password as MD5 hash
        """
        try:
            self._fw.log_debug("Env variable P4PASSWD is: %s" % os.environ.get('P4PASSWD'))
            md5_str = hashlib.md5(password.encode("utf")).hexdigest()
            # md5_str = hashlib.md5(password).hexdigest()
            md5_str = md5_str.upper()
            self._fw.log_debug("Storing password as Md5 hash: %s" % md5_str)
            self._fw.log_debug("Setting env variable P4PASSWD as: %s" % md5_str)
            os.environ["P4PASSWD"] = md5_str

            cmd_arg = "P4PASSWD={}".format(md5_str)
            cmd = ['set', cmd_arg]
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, env=os.environ)
            std_out, std_err = process.communicate()

            self._fw.log_debug("env variable P4PASSWD is: %s" % os.environ.get('P4PASSWD'))
        except:
            self._fw.log_debug("Unable to store password")
            pass

    def _prompt_for_password(self, error_msg, parent_widget):
        """
        Prompt the user for their P4 password.  This must be run in the main thread.

        :param error_msg:       Error message to display in the prompt dialog.
        :param parent_widget:   Parent QWidget to for the prompt dialog.
        :returns:               Tuple containing (dialog result, password)
        """
        # show the password entry dialog:
        from ..widgets import PasswordForm
        res, widget = self._fw.engine.show_modal("Perforce Password", self._fw, PasswordForm,
                                                 self._p4.port, self._p4.user, (parent_widget is None),
                                                 error_msg, parent_widget)

        return (res, widget.password)

    def _on_browse_workspace(self, widget):
        """
        Called when the user clics on the Browse button.

        :param widget: Parent dialog for the workspace browser.
        """
        if not self._do_connect_and_login(widget):
            return

        # prompt user to select workspace:
        ws_name = self._prompt_for_workspace(self._p4.user, widget.workspace, widget)
        if ws_name:
            widget.workspace = ws_name

    def _on_open_connection(self, widget):
        """
        Called when the user clicks Connect on the connection dialog.

        :param widget: The OpenConnectionForm object.
        """
        if not widget.workspace:
            return

        if not self._do_connect_and_login(widget):
            return

        # make sure the workspace is valid:
        try:
            self._validate_workspace(widget.workspace, widget.user)
            self._p4.client = str(widget.workspace)
            self.log('Connecting using workspace: {} ...'.format(self._p4.client))

        except TankError as e:
            # likely that the user isn't valid!
            QtGui.QMessageBox.information(widget, "Invalid Perforce Workspace!",
                                          ("Workspace '%s' is not valid for user '%s' on the Perforce server"
                                           ":\n\n    '%s'\n\n%s" % (widget.workspace, widget.user, widget.server, e)))
            return

        # success so lets close the widget!
        self.log('Connected!! ')
        widget.close()

    def _do_connect_and_login(self, widget):
        """
        Connects to the server, validates the connection and authenticates.

        :param widget: The OpenConnectionForm object.
        """
        self.log("_do_connect_and_login ...")
        if not widget.user:
            sg_user = sgtk.util.get_current_user(self._fw.sgtk)
            self.log('sg_user: {} ...'.format(sg_user))
            msg = ("Unable to browse Perforce Workspaces without a corresponding "
                   "Perforce username for Shotgun user:\n\n   '%s'" % (sg_user["name"] if sg_user else "Unknown"))
            QtGui.QMessageBox.warning(widget, "Unknown Perforce User!", msg)
            return False

        server = self.p4_server
        self.log('server: {} ...'.format(server))
        try:
            # ensure we are connected:
            self.log('ensure we are connected ...')
            if not self._p4 or not self._p4.connected():
                self.connect_to_server()
        except TankError as e:
            QtGui.QMessageBox.information(widget, "Perforce Connection Failed",
                                          "Failed to connect to Perforce server:\n\n    '%s'\n\n%s" % (server, e))
            return False
        self.log('We are connected')
        # ensure that the connection is trusted:
        self.log('ensure that the connection is trusted ...')
        try:
            is_trusted, _ = self._ensure_connection_is_trusted(True, widget)
            if not is_trusted:
                return False
        except TankError as e:
            QtGui.QMessageBox.information(widget, "Perforce Connection Not Trusted",
                                          "The connection to the Perforce server:\n\n    '%s'\n\is not trusted: %s" % (server, e))
            return False
        self.log('connection is trusted')
        self.log('make sure the current user is logged in ...')
        try:
            # make sure the current user is logged in:
            self._login_user(widget.user, widget)
        except TankError as e:
            # likely that the user isn't valid!
            QtGui.QMessageBox.information(widget, "Perforce Log-in Failed",
                                          ("Failed to log-in user '%s' to the Perforce server:\n\n    '%s'\n\n%s"
                                           % (widget.user, server, e)))
            return False

        self.log('current user is logged in')
        return True

    def _get_template(self):
        template_name = ""
        if self.p4_server.startswith("swc"):
            template_name =  "sgtk_Ark2Depot_master"
        elif self.p4_server.startswith("ssl"):
            template_name = "sgtk_devaDepot_master"
        return template_name

    def _sgtk_workspace(self):
        """
        Fetches the Sgtk-created workspace for perforce or creates one if it does not
        exist.

        :returns: The name of the sgtk workspace.
        """

        p4 = self.connection
        project_name = self._fw.sgtk.pipeline_configuration._project_name
        root_path = os.path.abspath(os.path.join(self._fw.sgtk.roots.get('primary'), os.pardir))  # one directory above project root
        template_name = "sgtk_{}_master".format(project_name)  # sgtk_proj_master
        self.log('root_path is {}'.format(root_path))
        self.log('template_name is {}'.format(template_name))
        hostname = socket.gethostname()
        workspace_name = "sgtk_{}_{}_{}".format(project_name, p4.user, hostname)  # sgtk_proj_username_hostname
        self.log('workspace_name is {}'.format(workspace_name))
        workspaces = [c["client"].lower() for c in p4.run("clients")]
        #self.log('workspaces are ... {}'.format(workspaces))

        if workspace_name.lower() in workspaces:
            self._fw.log_debug("Existing workspace found: {}".format(workspace_name))
            return workspace_name
        else:
            if template_name not in workspaces:
                if self.p4_server in self.templates:
                    template_name = self.templates[self.p4_server]
                    if template_name not in workspaces:
                        template_name = self._get_template()
                else:
                    template_name = self._get_template()
                if template_name not in workspaces:
                    self._fw.log_error("Template workspace '{}' not found! Contact your admin.".format(template_name))
                    return None

        self._fw.log_debug("Creating new workspace: {}".format(workspace_name))
        try:
            # create a new client workspace spec from the project template
            client = p4.fetch_client("-t", template_name, workspace_name)
            # set the root to be one-level above the sgtk project root and give a desc
            client._root = root_path
            client._description = "Sgtk-generated workspace based on {}".format(template_name)
            # save the client workspace to p4 so we can access it
            p4.save_client(client)
        except:
            self._fw.log_error("Error creating new workspace: '{}'! Contact your admin.".format(template_name))
            return None

        return workspace_name

    def _get_current_workspace(self):
        """
        Returns the current workspace based on the frameworks settings or P4CLIENT
        if no setting was found.

        :returns: The name of the current workspace.
        """
        workspace = ""
        if self._fw.context.project:
            settings = UserSettings("user_details")
            workspace = settings.get_client(self._fw.context.project["id"])

        if not workspace:
            workspace = self._sgtk_workspace()

        if not workspace:
            # see if P4CLIENT is set in the environment:
            env_val = os.environ.get("P4CLIENT")
            if env_val:
                workspace = env_val

        self._fw.log_debug("Current workspace is '%s'" % workspace)
        return workspace

    def _save_current_workspace(self, workspace):
        """
        Persists the current workspace name.

        :param workspace: Name of the new current workspace.
        """
        if self._fw.context.project:
            settings = UserSettings("user_details")
            return settings.set_client(self._fw.context.project["id"], workspace)

    def _validate_workspace(self, workspace, user):
        """
        Checks if the workspace exists and is usable by a user.

        :param workspace: Name of the workspace to validate.
        :param user: User to check for ownership of the workspace.

        :raises TankError: Raised if workspace doesn't exist or is not owned by the
            user.
        """
        try:
            workspaces = self._p4.run_clients("-e", str(workspace))
            self.log('run_clientsworkspaces: {}'.format(workspaces))
        except P4Exception as e:
            raise SgtkP4Error(self._p4.errors[0] if self._p4.errors else str(e))

        if not workspaces:
            raise TankError("Workspace '%s' does not exist!" % (workspace))

        ws_users = [ws.get("Owner") for ws in workspaces]
        if user not in ws_users:
            raise TankError("Workspace '%s' is not owned by user '%s'" % (workspace, user))

    def _login_required_user(self, min_timeout=300):
        """
        Determine if the specified user is required to log in.
        """
        # first, check to see if the user is required to log in:
        self.log('is login required?')
        """
        users = []
        try:
            # This will raise a P4Exception if the user isn't valid:
            # (TODO) - check this wasn't just a warning!
            users = self._p4.run_users(self._p4.user)
        except P4Exception as e:
            raise SgtkP4Error(self._p4.errors[0] if self._p4.errors else str(e))
        self.log('users: {} '.format(users))
        if not users:
            # just in case it didn't raise an exception!
            self.log('There are no users')
            return True
        """
        # get the list of tickets for the current user
        try:
            p4_res = self._p4.run_login("-s")
            self.log('p4_res: {} '.format(p4_res))
            if not p4_res:
                # no ticket so login required
                self.log('no ticket so login required')
                return True
        except P4Exception:
            # exception raised because user isn't logged in!
            # (TODO) - are there other exceptions that could be raised?
            self.log('exception raised because user is not logged in')
            return True

        # p4_res is of the form:
        # [{'TicketExpiration': '43026', 'User': 'Alan'}]
        for ticket_status in p4_res:
            timeout = 0
            try:
                timeout = int(ticket_status.get("TicketExpiration", "0"))
            except ValueError:
                timeout = 0
            if timeout >= min_timeout:
                # user is logged in and has enough
                # time remaining
                self.log('user is logged in and has enough time remaining')
                return False
        self.log('user is not logged in!')
        # user isn't logged in!
        return True

    def _login_required(self, min_timeout=300):
        """
        Determine if the specified user is required to log in.
        """
        # first, check to see if the user is required to log in:
        self.log('first, check to see if the user is required to log in')
        users = []
        try:
            # This will raise a P4Exception if the user isn't valid:
            # (TODO) - check this wasn't just a warning!
            users = self._p4.run_users(self._p4.user)
        except P4Exception as e:
            raise SgtkP4Error(self._p4.errors[0] if self._p4.errors else str(e))
        self.log('users: {} '.format(users))
        if not users:
            # just in case it didn't raise an exception!
            self.log('Threre are no users')
            return True

        # users = [...{'Password': 'enabled'}...]
        if not users[0].get("Password") == "enabled":
            self.log('Password is enabled')
            return False

        # get the list of tickets for the current user
        try:
            p4_res = self._p4.run_login("-s")
            self.log('p4_res: {} '.format(p4_res))
            if not p4_res:
                # no ticket so login required
                self.log('no ticket so login required')
                return True
        except P4Exception:
            # exception raised because user isn't logged in!
            # (TODO) - are there other exceptions that could be raised?
            self.log('exception raised because user is not logged in')
            return True

        # p4_res is of the form:
        # [{'TicketExpiration': '43026', 'User': 'Alan'}]
        for ticket_status in p4_res:
            timeout = 0
            try:
                timeout = int(ticket_status.get("TicketExpiration", "0"))
            except ValueError:
                timeout = 0
            if timeout >= min_timeout:
                # user is logged in and has enough
                # time remaining
                self.log('user is logged in and has enough time remaining')
                return False
        self.log('user is not logged in!')
        # user isn't logged in!
        return True

    def _get_p4_server(self):
        """
        Get P4 server based on sg_region
        """
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

    def log(self, msg, error=0):
        if logger:
            if error:
                logger.warn(msg)
            else:
                logger.info(msg)
        print(msg)


def connect(allow_ui=True, user=None, password=None, workspace=None, progress=None):
    """
    Connect to Perforce

    :param allow_ui:    If True and connecting requires user input (e.g. Password or workspace) then
                        UI will be shown
    :param user:        If specified, this will override the current Perforce user
    :param password:    If specified, this will be used to log in the Perforce user
    :param workspace:   If specified, this will be used as the workspace for the Perforce user.  If
                        set to '' then no workspace will be set for the new connection
    :returns P4:        A new Perforce connection instance if successful
    """
    fw = sgtk.platform.current_bundle()
    try:
        connection = ConnectionHandler(fw).connect(allow_ui, user, password, workspace)
        if progress:
            connection.progress = ProgressHandler()
        return connection
    except SgtkP4TCPConnectionError:
        raise


def connect_with_dialog():
    """
    Show the Perforce connection dialog

    :returns P4:    A new Perforce connection instance if successful
    """
    fw = sgtk.platform.current_bundle()
    return ConnectionHandler(fw).connect_with_dlg()
