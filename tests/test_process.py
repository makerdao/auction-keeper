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

import time

import os

import psutil
import pytest

from auction_keeper.process import Process


class TestProcess:
    def setup_method(self):
        pass

    @pytest.mark.timeout(15)
    def test_should_read_json_document(self):
        process = Process("./tests/models/output-once.sh")
        process.start()

        while process.read() != {'key1': 'value1', 'key2': 2}:
            time.sleep(0.1)

        process.stop()

    @pytest.mark.timeout(15)
    def test_should_read_last_available_json_document(self):
        process = Process("./tests/models/output-multiple.sh")
        process.start()

        while process.read() != {'key': 'value3'}:
            time.sleep(0.1)

        process.stop()

    @pytest.mark.timeout(15)
    def test_should_read_and_write(self):
        process = Process("./tests/models/output-echo.sh")
        process.start()

        time.sleep(1)
        assert process.read() is None

        for value in ['value1', 'value2', 'value3']:
            process.write({'key': value})
            while process.read() != {'key': value}:
                time.sleep(0.1)

        process.stop()

    @pytest.mark.timeout(15)
    def test_should_kill_process_on_stop(self):
        process = Process("./tests/models/output-echo.sh")
        process.start()

        while process.pid is None:
            time.sleep(0.1)

        assert process.pid is not None
        assert psutil.pid_exists(process.pid)

        process.stop()

        # todo fails in macOS
        # while psutil.pid_exists(process.pid):
        #     time.sleep(0.1)
