# Copyright 2013 GridCentric Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from novaclient.exceptions import ClientException
import py.test

from . import harness
from . logger import log
from . import requirements
from . util import assert_raises
from . host import Host

class TestMigration(harness.TestCase):

    def test_migration_one(self, image_finder):
        if self.harness.config.skip_migration_tests:
            py.test.skip('Skipping migration tests')
        if len(self.harness.config.hosts) < 2:
            py.test.skip('Need at least 2 hosts to do migration.')
        with self.harness.booted(image_finder, agent=False) as master:
            host = master.get_host()
            dest = Host([h for h in self.config.hosts if h != host.id][0], self.harness.config)
            assert host.id != dest.id
            master.migrate(host, dest)

    def test_migration_errors(self, image_finder):
        if self.harness.config.skip_migration_tests:
            py.test.skip('Skipping migration tests')
        if len(self.harness.config.hosts_without_gridcentric) == 0:
            py.test.skip('Need at least one host without gridcentric to test for migration errors.')
        with self.harness.booted(image_finder, agent=False) as master:
            host = master.get_host()

            def fail_migrate(dest):
                log.info('Expecting Migration %s to %s to fail', str(master.id), dest)
                master.breadcrumbs.add('pre expected fail migration to %s' % dest.id)
                e = assert_raises(ClientException,
                                  master.migrate,
                                  host, dest)
                assert e.code / 100 == 4 or e.code / 100 == 5
                master.assert_alive(host)
                master.breadcrumbs.add('post expected fail migration to %s' % dest.id)

            # Destination does not exist.
            fail_migrate(Host('this-host-does-not-exist', self.harness.config))

            # Destination does not have gridcentric.
            dest = Host(self.config.hosts_without_gridcentric[0], self.harness.config)
            fail_migrate(dest)

            # Cannot migrate to self.
            fail_migrate(host)

    def test_back_and_forth(self, image_finder):
        if self.harness.config.skip_migration_tests:
            py.test.skip('Skipping migration tests')
        if len(self.harness.config.hosts) < 2:
            py.test.skip('Need at least 2 hosts to do migration.')
        with self.harness.booted(image_finder, agent=False) as master:
            host = master.get_host()
            dest = Host([h for h in self.config.hosts if h != host.id][0], self.harness.config)
            assert host.id != dest.id
            master.migrate(host, dest)
            master.migrate(dest, host)
            master.migrate(host, dest)
            master.migrate(dest, host)

    # We require host targetting to check hooks availability
    # *before* booting a guest, thus saving time
    @harness.requires(requirements.AVAILABILITY_ZONE)
    def test_migration_rollback(self, image_finder):
        if self.harness.config.skip_migration_tests:
            py.test.skip('Skipping migration tests')
        if len(self.harness.config.hosts) < 2:
            py.test.skip('Need at least 2 hosts to do migration.')
        source_host_name    = self.config.hosts[0]
        source_host         = Host(source_host_name, self.config)
        if not source_host.check_supports_hooks():
            py.test.skip("Host %s does not have cobalt hooks enabled." %\
                         source_host_name)
        dest_host = Host(self.config.hosts[1], self.harness.config)
        assert source_host.id != dest_host.id
        log.debug("Migration rollback source host %s" % source_host_name)
        log.debug("Migration rollback dest host %s" % dest_host.id)
        with self.harness.booted(image_finder, agent=False, host=source_host) as master:
            assert getattr(master, 'id') is not None
            with source_host.with_hook("01_post_bless", """#!/bin/bash
set -e
echo "Post bless hook args: $@" >&2
[ $# -eq 6 ]
[ $1 == %s ]
[ $6 == migration ]
[[ $5 == mcdist://* ]]
URL=${5#mcdist://}
ADDR=$(echo $URL | cut -d '|' -f 1)
# For good luck
sleep 3
[ $(netstat -plun | grep -E 'vmsd\s*$' | awk -v addr="$ADDR" '$4==addr {print $NF}' | wc -l) -eq 1 ]
PID=$(netstat -plun | grep -E 'vmsd\s*$' | awk -v addr="$ADDR" '$4==addr {print $NF}' | cut -d '/' -f 1)
kill -9 $PID
""" % master.id) as hook:
                # The hook above will kill the memsrv after the bless phase of migration
                # should be fun...
                e = assert_raises(AssertionError,
                          master.migrate,
                          source_host, dest_host)
                master.assert_alive(source_host)
                e = assert_raises(AssertionError,
                          master.assert_alive,
                          dest_host)

