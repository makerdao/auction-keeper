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
    def test_should_read_multiple_json_documents(self):
        process = Process("./tests/models/output-multiple.sh")
        process.start()

        while process.read() != {'key': 'value1'}:
            time.sleep(0.1)

        while process.read() != {'key': 'value2'}:
            time.sleep(0.1)

        while process.read() != {'key': 'value3'}:
            time.sleep(0.1)

        process.stop()

    @pytest.mark.timeout(15)
    def test_should_skip_invalid_json_documents(self):
        process = Process("./tests/models/output-invalid.sh")
        process.start()

        while process.read() != {'key': 'value1'}:
            time.sleep(0.1)

        while process.read() != {'key': 'value2'}:
            time.sleep(0.1)

        while process.read() != {'key': 'value3'}:
            time.sleep(0.1)

        process.stop()

    @pytest.mark.timeout(15)
    def test_should_return_none_from_read_if_nothing_to_read(self):
        process = Process("./tests/models/terminate-voluntarily.sh")

        process.start()
        while process.running:
            assert process.read() is None

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

    def test_should_read_long_json_documents(self):
        process = Process("./tests/models/output-long.sh")
        process.start()

        time.sleep(1)

        doc = process.read()

        assert doc is not None
        assert len(doc) == 65

    @pytest.mark.timeout(10)
    def test_should_not_block_on_many_writes_if_no_input_being_received_by_the_process(self):
        process = Process("./tests/models/output-once.sh")
        process.start()

        for _ in range(100000):
            process.write({'aaa': 'bbb'})

    @pytest.mark.timeout(15)
    def test_should_terminate_process_on_broken_input_pipe(self):
        process = Process("./tests/models/break-pipe.sh")
        process.start()

        # so the process has some time to break the pipe
        time.sleep(1)

        for _ in range(10):
            process.write({'aaa': 'bbb'})

        time.sleep(5)

        assert process.running is False

    @pytest.mark.timeout(15)
    def test_should_kill_process_on_stop(self):
        process = Process("./tests/models/output-echo.sh")

        process.start()
        while not process.running:
            time.sleep(0.1)

        process.stop()
        while process.running:
            time.sleep(0.1)

    def test_should_set_running_to_true_immediately_after_start(self):
        process = Process("./tests/models/output-echo.sh")
        process.start()

        assert process.running

    def test_should_not_let_start_the_process_twice(self):
        process = Process("./tests/models/output-echo.sh")
        process.start()

        with pytest.raises(Exception):
            process.start()

    @pytest.mark.timeout(15)
    def test_should_let_start_the_process_again_after_it_got_stopped(self):
        process = Process("./tests/models/output-echo.sh")

        process.start()
        while not process.running:
            time.sleep(0.1)

        process.stop()
        while process.running:
            time.sleep(0.1)

        process.start()
        while not process.running:
            time.sleep(0.1)

    @pytest.mark.timeout(15)
    def test_should_let_start_the_process_again_after_it_terminated_voluntarily(self):
        process = Process("./tests/models/terminate-voluntarily.sh")

        process.start()
        while process.running:
            time.sleep(0.1)

        process.start()
        while not process.running:
            time.sleep(0.1)
