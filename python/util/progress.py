import sgtk
from P4 import P4Exception, Progress
logger = sgtk.LogManager.get_logger(__name__)
from datetime import datetime, timedelta

from sgtk.platform.qt import QtCore


def sizeof_fmt(num, suffix="B"):
    num *= 1024.0
    if suffix in ["b", "bps"]:
        num *= 8
    for unit in ["", "K", "M", "G", "T", "P", "E", "Z"]:
        if abs(num) < 1024.0:
            return "{num:3.1f}{unit}{suffix}".format(num=num,unit=unit,suffix=suffix)
        num /= 1024.0
    return "{num:.1f}Y{suffix}".format(num=num,suffix=suffix)

class ProgressSignaller(QtCore.QObject):
    """
    Create signaller class for to signal from the progress handler
    """
    
    total_size = QtCore.Signal(str)
    transfer_rate = QtCore.Signal(str)

    description = QtCore.Signal(str)
    time_remaining = QtCore.Signal(str)
    percent_done = QtCore.Signal(float)
    finished = QtCore.Signal()


class ProgressHandler( Progress ):

    def __init__(self):
        """
        To be used as a module handler to receive progress updates from P4 server when
        another blocking call is being utilized. 
        For example, when a single call for "submit change" is occurring, the p4 module is
        still receiving progress updates from the server and theyre handled via this class. 
        """
        Progress.__init__(self)

        self.signaller = ProgressSignaller()
        self.description = self.signaller.description
        self.time_remaining = self.signaller.time_remaining
        self.finished = self.signaller.finished
        self.percent_done = self.signaller.percent_done
        self.total_size = self.signaller.total_size
        self.transfer_rate = self.signaller.transfer_rate

        self.invoked = 0
        self.curr_total = 0
        self.curr_description = ""

        # markers to be able to derive eta
        self.time_register = datetime.now()
        self.size_register = 1
        self.percent_complete = 0.0
        self.completed_since_last_poll = 0.0


    def init(self, type):
        logger.info(type)

    def setDescription(self, description, unit):
        self.curr_description = description
        logger.info("{}, {}".format(description, unit))

    def setTotal(self, total):
        self.curr_total = total
        self.total_size.emit(sizeof_fmt(self.curr_total))

    def update(self, position):
        try:
        
            size_transfered = position-self.size_register

            percent_completed = float(position)/float(self.curr_total)
            percent_left = 1.0-percent_completed
            self.completed_since_last_poll = percent_completed - self.percent_complete
            updates_left = percent_left/self.completed_since_last_poll

            now = datetime.now()
            update_interval =  now - self.time_register
            
            update_interval_seconds = float(update_interval.microseconds)/1000000
            size_transfered_per_second = sizeof_fmt(int(size_transfered/update_interval_seconds), suffix="bps")

            estimated_time_left = timedelta(microseconds=update_interval.microseconds*updates_left)
            self.percent_complete = percent_completed

            self.time_register = now
            self.size_register = position

            # emit qt signals
            self.description.emit(self.curr_description)
            self.time_remaining.emit(str(estimated_time_left))
            self.percent_done.emit(self.percent_complete*100)
            self.transfer_rate.emit(size_transfered_per_second)

        except Exception as e:
            logger.warning("Could not handle progress: {}".format(e))

    def done(self, fail):
        logger.info(fail)
        self.finished.emit()


