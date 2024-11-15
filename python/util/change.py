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
Common utilities for working with Perforce changes
"""
from P4 import P4Exception
from sgtk import TankError, LogManager

log = LogManager.get_logger(__name__)


def create_change(p4, description):
    """
    Helper method to create a new change
    """

    # create a new changelist:
    new_change = None
    try:
        # fetch a new change, update the description, and save it:
        change_spec = p4.fetch_change()
        change_spec._description = str(description)
        # have to clear the file list as otherwise it would contain everything
        # in the default changelist!
        change_spec._files = []
        p4_res = p4.save_change(change_spec)

        if p4_res:
            try:
                # p4_res should be like: ["Change 25 created."]
                new_change_id = int(p4_res[0].split()[1])
                new_change = str(new_change_id)
            except ValueError:
                raise TankError("Perforce: Failed to extract new change id from '%s'" % p4_res)

    except P4Exception as e:
        raise TankError("Perforce: %s" % (p4.errors[0] if p4.errors else e))

    if new_change == None:
        raise TankError("Perforce: Failed to create new change!")

    return new_change


def add_to_change(p4, change, file_paths, dry_run=False):
    """
    Add the specified files to the specified change
    """
    try:
        # use reopen command which works with local file paths.
        # fetch/modify/save_change only works with depot paths!
        if dry_run:
            # # -n flag is to do a dry run
            p4.run_reopen("-c", str(change), "-n", file_paths)
        else:
            # no -n flag, so this will actually run the command
            p4.run_reopen("-c", str(change), file_paths)
    except P4Exception as e:
        raise TankError("Perforce: %s" % (p4.errors[0] if p4.errors else e))


def find_change_containing(p4, path):
    """
    Find the current change that the specified path is in.
    """
    try:
        p4_res = p4.run_fstat(path)
    except P4Exception as e:
        raise TankError("Perforce: %s" % (p4.errors[0] if p4.errors else e))

    change = p4_res[0].get("change")
    return change


def submit_change(p4, change, dry_run=False):
    """
    Submit the specified change
    """
    try:
        change_spec = p4.fetch_change("-o", str(change))
        if dry_run:
            # -n flag is to do a dry run
            submit = p4.run_submit("-n", change_spec)
        else:
            # no -n flag, so this will actually run the command
            submit = p4.run_submit(change_spec)
        """
        run_submit returns a list of dicts, something like this:
        [{'change': '90', 'locked': '2'},
         "Possible string in here",
         {'action': 'edit',
          'depotFile': '//deva/Tool/ScorchedEarth/ToolCategory/ToolTestAsset/deva_ScorchedEarth_ToolTestAsset_concept.psd',
          'rev': '2'},
         {'action': 'edit',
          'depotFile': '//deva/Tool/ScorchedEarth/ToolCategory/ToolTestAsset/deva_ScorchedEarth_ToolTestAsset_concept_alt.psd',
          'rev': '4'},
         {'submittedChange': '90'}]
        """
        log.debug("Return of run_submit: {}".format(submit))
        return submit
    except P4Exception as e:
        raise TankError("Perforce: %s" % (p4.errors[0] if p4.errors else e))


def get_change_details(p4, changes):
    """
    Get the changes details for one or more changes

    :param p4:         The Perforce connection
    :param changes:    The list of changes to query Perforce for
    :returns dict:     A dictionary mapping each change to the details found
    """
    try:
        p4_res = p4.run_describe(changes)
    except P4Exception as e:
        raise TankError("Perforce: %s" % (p4.errors[0] if p4.errors else e))

    p4_res_lookup = {}
    for item in p4_res:
        change = item.get("change")
        if not change:
            continue
        p4_res_lookup[change] = item

    change_details = {}
    for change in changes:
        details = p4_res_lookup.get(change)
        change_details[change] = details

    return change_details
