import sgtk
from P4 import P4Exception, Progress
logger = sgtk.LogManager.get_logger(__name__)
from datetime import datetime, timedelta

from sgtk.platform.qt import QtCore

class ProgressSignaller(QtCore.QObject):
    """
    Create signaller class for to signal from the progress handler
    """
    description = QtCore.Signal(str)
    time_remaining = QtCore.Signal(str)
    percent_done = QtCore.Signal(float)
    finished = QtCore.Signal()


class ProgressHandler( Progress ):

    def __init__(self):
        Progress.__init__(self)

        self.signaller = ProgressSignaller()
        self.description = self.signaller.description
        self.time_remaining = self.signaller.time_remaining
        self.finished = self.signaller.finished
        self.percent_done = self.signaller.percent_done

        self.invoked = 0
        self.curr_total = 0
        self.curr_description = ""

        # markers to be able to derive eta
        self.time_register = datetime.now()
        self.percent_complete = 0.0
        self.completed_since_last_poll = 0.0


    def init(self, type):
        logger.info(type)

    def setDescription(self, description, unit):
        self.curr_description = description
        logger.info("{}, {}".format(description, unit))

    def setTotal(self, total):
        self.curr_total = total

    def update(self, position):
        percent_completed = float(position)/float(self.curr_total)
        percent_left = 1.0-percent_completed
        self.completed_since_last_poll = percent_completed - self.percent_complete
        updates_left = percent_left/self.completed_since_last_poll

        now = datetime.now()
        update_interval =  now - self.time_register
        
        estimated_time_left = timedelta(microseconds=update_interval.microseconds*updates_left)
        self.percent_complete = percent_completed
        self.time_register = now

        # emit qt signals
        self.description.emit(self.curr_description)
        self.time_remaining.emit(str(estimated_time_left))
        self.percent_done.emit(self.percent_complete*100)

    def done(self, fail):
        logger.info(fail)
        self.finished.emit()


