#!/usr/bin/env python
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0
#
# Authors:
# - Miha Muskinja, miha.muskinja@cern.ch, 2020

import json
import os
import time
import traceback

from pilot.api.es_data import StageOutESClient
from pilot.common.exception import PilotException, StageOutFailure, ErrorCodes

from pilot.eventservice.esprocess.esprocess import ESProcess
from pilot.info.filespec import FileSpec
from pilot.info import infosys
from pilot.util.auxiliary import get_logger
from pilot.util.container import execute

from .baseexecutor import BaseExecutor

import logging
logger = logging.getLogger(__name__)

"""
Generic Executor with one process to manage EventService
"""


class GenericExecutor(BaseExecutor):
    def __init__(self, **kwargs):
        super(GenericExecutor, self).__init__(**kwargs)
        self.setName("GenericExecutor")

        self.__queued_out_messages = []
        self.__last_stageout_time = None
        self.__all_out_messages = []

        self.proc = None
        self.exit_code = None

    def is_payload_started(self):
        return self.proc.is_payload_started() if self.proc else False

    def get_pid(self):
        return self.proc.pid if self.proc else None

    def get_exit_code(self):
        return self.exit_code

    def update_finished_event_ranges(self, out_messagess):
        """
        Update finished event ranges

        :param out_messages: messages from AthenaMP.
        """
        if len(out_messagess) == 0:
            return

        event_ranges = []
        for out_msg in out_messagess:
            event_ranges.append({"eventRangeID": out_msg['id'], "eventStatus": 'finished', "fileLocation": out_msg['output']})
        event_range_status = {"esOutput": {"numEvents": len(event_ranges)},
                              "eventRanges": event_ranges}
        event_range_message = {'version': 1, 'eventRanges': json.dumps([event_range_status])}
        self.update_events(event_range_message)

        job = self.get_job()
        job.nevents += len(event_ranges)

    def update_failed_event_ranges(self, out_messagess):
        """
        Update failed event ranges

        :param out_messages: messages from AthenaMP.
        """
        if len(out_messagess) == 0:
            return

        event_ranges = []
        for message in out_messagess:
            status = message['status'] if message['status'] in ['failed', 'fatal'] else 'failed'
            # ToBeFixed errorCode
            event_ranges.append({"errorCode": 1220, "eventRangeID": message['id'], "eventStatus": status})
            event_range_message = {'version': 0, 'eventRanges': json.dumps(event_ranges)}
            self.update_events(event_range_message)

    def handle_out_message(self, message):
        """
        Handle ES output or error messages hook function for tests.

        :param message: a dict of parsed message.
                        For 'finished' event ranges, it's {'id': <id>, 'status': 'finished', 'output': <output>, 'cpu': <cpu>,
                                                           'wall': <wall>, 'message': <full message>}.
                        Fro 'failed' event ranges, it's {'id': <id>, 'status': 'failed', 'message': <full message>}.
        """
        job = self.get_job()
        log = get_logger(job.jobid, logger)
        log.info("Handling out message: %s" % message)

        self.__all_out_messages.append(message)

        if message['status'] in ['failed', 'fatal']:
            self.update_failed_event_ranges([message])
        else:
            self.__queued_out_messages.append(message)

    def stageout_es(self, force=False):
        """
        Stage out event service outputs.

        """
        job = self.get_job()
        if len(self.__queued_out_messages):
            if force or self.__last_stageout_time is None or (time.time() > self.__last_stageout_time + job.infosys.queuedata.es_stageout_gap):
                out_messages = []
                while len(self.__queued_out_messages) > 0:
                    out_messages.append(self.__queued_out_messages.pop())
                self.update_finished_event_ranges(out_messages)

    def clean(self):
        """
        Clean temp produced files
        """
        job = self.get_job()
        log = get_logger(job.jobid, logger)

        for msg in self.__all_out_messages:
            if msg['status'] in ['failed', 'fatal']:
                pass
            elif 'output' in msg:
                try:
                    log.info("Removing es premerge file: %s" % msg['output'])
                    # os.remove(msg['output'])
                except Exception as e:
                    log.error("Failed to remove file(%s): %s" % (msg['output'], str(e)))
        self.__queued_out_messages = []
        self.__last_stageout_time = None
        self.__all_out_messages = []

        if self.proc:
            self.proc.stop()
            while self.proc.is_alive():
                time.sleep(0.1)

        self.stop_communicator()

    def run(self):
        """
        Initialize and run ESProcess.
        """
        try:
            logger.info("starting ES GenericExecutor with thread ident: %s" % (self.ident))
            if self.is_set_payload():
                payload = self.get_payload()
            elif self.is_retrieve_payload():
                payload = self.retrieve_payload()
            else:
                logger.error("Payload is not set but is_retrieve_payload is also not set. No payloads.")

            job = self.get_job()
            log = get_logger(job.jobid, logger)
            log.info("payload: %s" % payload)

            log.info("Starting ESProcess")
            proc = ESProcess(payload)
            self.proc = proc
            log.info("ESProcess initialized")

            proc.set_get_event_ranges_hook(self.get_event_ranges)
            proc.set_handle_out_message_hook(self.handle_out_message)

            log.info('ESProcess starts to run')
            proc.start()
            log.info('ESProcess started to run')

            exit_code = None
            try:
                iteration = long(0)  # Python 2
            except Exception:
                iteration = 0  # Python 3
            while proc.is_alive():
                iteration += 1
                if self.is_stop():
                    log.info('Stop is set. breaking -- stop process pid=%s' % proc.pid)
                    proc.stop()
                    break
                self.stageout_es()

                exit_code = proc.poll()
                if iteration % 60 == 0:
                    log.info('running: iteration=%d pid=%s exit_code=%s' % (iteration, proc.pid, exit_code))
                time.sleep(5)

            while proc.is_alive():
                time.sleep(1)
            log.info("ESProcess finished")

            self.stageout_es(force=True)
            self.clean()

            self.exit_code = proc.poll()

        except Exception as e:
            logger.error('Execute payload failed: %s, %s' % (str(e), traceback.format_exc()))
            self.clean()
            self.exit_code = -1
        logger.info('ES generic executor finished')
