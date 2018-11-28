# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2018 reverendus, bargst
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

    def __init__(self, command_with_arguments: str):
        self.command_with_arguments = command_with_arguments
        self._thread = None
        self._terminate = False
        self._read_lock = threading.RLock()
        self._read_queue = []
        self._write_lock = threading.RLock()
        self._write_queue = []

    def _run(self):
        try:
            process = Popen(self.command_with_arguments.split(' '), stdin=PIPE, stdout=PIPE, stderr=PIPE, shell=False)
            self._set_nonblock(process.stdout)
            self._set_nonblock(process.stderr)

            self.logger.info(f"Process '{self.command_with_arguments}' (pid #{process.pid}) started")
        except:
            self.logger.exception(f"Failed to start process '{self.command_with_arguments}'")
            return

        while process.poll() is None:
            if self._terminate:
                process.kill()
                break

            # Read from stdout
            try:
                lines = read(process.stdout.fileno(), 102400).decode('utf-8').splitlines()

                with self._read_lock:
                    for line in lines:
                        self.logger.debug(f"Model process #{process.pid} read: {line}")

                        try:
                            self._read_queue.append(json.loads(line))
                        except JSONDecodeError:
                            self.logger.exception(f"Incorrect JSON message received from model #{process.pid} process")
            except OSError:
                pass  # the os throws an exception if there is no data

            # Read from stderr
            try:
                lines = read(process.stderr.fileno(), 102400).decode('utf-8').splitlines()
                for line in lines:
                    self.logger.info(f"Model process #{process.pid} output: {line}")
            except OSError:
                pass  # the os throws an exception if there is no data

            # Write to stdin
            while True:
                with self._write_lock:
                    if len(self._write_queue) == 0:
                        break

                    line = self._write_queue.pop(0)

                self.logger.debug(f"Model process #{process.pid} write: {line}")

                try:
                    process.stdin.write((line + '\n').encode('ascii'))
                    process.stdin.flush()
                except BrokenPipeError:
                    self.logger.exception(f"Model process #{process.pid} caused broken pipe, terminating the process")
                    self._terminate = True

                    break

            time.sleep(0.01)

        self.logger.info(f"Process '{self.command_with_arguments}' (pid #{process.pid}) terminated")

    @staticmethod
    def _set_nonblock(pipe):
        flags = fcntl(pipe, F_GETFL)  # get current p.stdout flags
        fcntl(pipe, F_SETFL, flags | O_NONBLOCK)

    @property
    def running(self):
        return self._thread and \
               self._thread.is_alive()

    def start(self):
        assert not self.running

        self._terminate = False
        self._read_queue.clear()
        self._write_queue.clear()

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def read(self) -> Optional[dict]:
        with self._read_lock:
            return self._read_queue.pop(0) if len(self._read_queue) > 0 else None

    def write(self, data: dict):
        assert isinstance(data, dict)

        with self._write_lock:
            self._write_queue.append(json.dumps(data, indent=None))

    def stop(self):
        assert self.running

        self._terminate = True
