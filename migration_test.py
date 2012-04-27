import os
import unittest

import harness

from logger import log
from config import default_config

class TestMigration(unittest.TestCase):

    def setUp(self):
        self.client = harness.create_client()
        self.server = harness.boot(self.client, 'TestMigration', default_config)
        self.ip = self.server.networks['base_network'][0]
        self.shell = harness.SecureShell(self.ip, default_config)
        self.breadcrumbs = harness.Breadcrumbs(self.shell)
        self.breadcrumbs.add('booted %s' % self.server.name)

    def get_host_dest(self):
        host = default_config.id_to_hostname(self.server.hostId)
        dest = default_config.other_hosts(host)[0]
        assert host != dest
        return host, dest

    def assert_migration_ok(self, dest):
        self.server.get()
        assert self.server.hostId == hostname_to_id(dest)
        harness.wait_for_ping(self.server, duration=5)
        harness.wait_for_ssh(self.shell, duration=5)

    def migrate(self, dest):
        log.info('Migrating %s to %s', str(self.server.id), dest)
        self.breadcrumbs.add('pre migration to %s' % dest)
        self.client.gcapi.migrate_instance(self.server.id, dest)
        self.assert_migration_ok(dest)
        self.breadcrumbs.add('post migration to %s' % dest)

    def test_simple(self):
        host, dest = self.get_host_dest()
        self.migrate(dest)
        self.server.delete()

    def test_back_and_forth(self):
        host, dest = self.get_host_dest()
        self.migrate(dest)
        self.migrate(host)
        self.migrate(dest)
        self.migrate(host)
        self.server.delete()

    def test_ip_address(self):
        host, dest = self.get_host_dest()
        dest_ip = socket.gethostbyaddr(dest)[2][0]
        self.client.gcapi.migrate_instance(self.server.id, dest_ip)
        self.server.get()
        assert self.server.hostId == hostname_to_id(dest)
        self.server.delete()

    def test_dest_does_not_exist(self):
        return
        dest = 'this-host-does-not-exist'
        #assert raises error
        self.client.gcapi.migrate_instance(self.server.id, dest)
        self.server.delete()
