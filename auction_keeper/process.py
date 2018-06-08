# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2018 reverendus
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import json
import logging
import threading
import time
from fcntl import fcntl, F_SETFL, F_GETFL
from json import JSONDecodeError
from os import O_NONBLOCK, read
from subprocess import Popen, PIPE
from typing import Optional


class Process:
    logger = logging.getLogger()

    def __init__(self, command: str):
        self.command = command
        self.process = None
        self.thread = None

        self._last_read = None
        self._last_read_lock = threading.RLock()

    def _run(self):
        self.process = Popen(self.command.split(' '), stdin=PIPE, stdout=PIPE, stderr=PIPE, shell=False)
        self._set_nonblock(self.process.stdout)
        self._set_nonblock(self.process.stderr)

        #TODO add some process identifiers to the log messages etc.
        #TODO log process created

        while True:
            try:
                lines = read(self.process.stdout.fileno(), 1024).decode('utf-8').splitlines()

                with self._last_read_lock:
                    for line in lines:
                        self.logger.debug(f"Model process stdout: {line}")

                        self._last_read = json.loads(line)
            except JSONDecodeError:
                self.logger.exception("Incorrect JSON message received from model process")
            except OSError:
                pass  # the os throws an exception if there is no data

            try:
                lines = read(self.process.stderr.fileno(), 1024).decode('utf-8').splitlines()
                for line in lines:
                    self.logger.debug(f"Model process output: {line}")
            except OSError:
                pass  # the os throws an exception if there is no data

            time.sleep(0.01)

    @staticmethod
    def _set_nonblock(pipe):
        flags = fcntl(pipe, F_GETFL) # get current p.stdout flags
        fcntl(pipe, F_SETFL, flags | O_NONBLOCK)

    @property
    def pid(self):
        return self.process.pid if self.process else None

    def start(self):
        assert(self.process is None)
        assert(self.thread is None)

        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def read(self) -> Optional[dict]:
        return self._last_read

    def write(self, data: dict):
        assert(isinstance(data, dict))

        data_str = json.dumps(data, indent=None)

        if self.process is not None:
            self.logger.debug(f"Sending data to the model process: {data_str}")

            self.process.stdin.write((data_str + '\n').encode('ascii'))
            self.process.stdin.flush()

        else:
            #TODO this isn't clean. think about changing
            #TODO maybe messages should be queued and sent from the thread we use to read them?
            self.logger.warning(f"Cannot send data to process as process hasn't started yet: {data_str}")

    def stop(self):
        assert(self.process is not None)

        self.process.kill()
        #TODO log process killed
