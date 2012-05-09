import os
import socket
import unittest

from gridcentric.nova.client.exceptions import HttpException

import harness

from logger import log
from config import default_config

class TestMigration(unittest.TestCase):

    def setUp(self):
        self.config = default_config
        self.client = harness.create_client()
        self.server = harness.boot(self.client, harness.test_name, self.config)
        self.ip = self.server.networks.values()[0][0]
        self.shell = harness.SecureShell(self.ip, self.config)
        self.breadcrumbs = harness.Breadcrumbs(self.shell)
        self.breadcrumbs.add('booted %s' % self.server.name)

    def get_host(self):
        return self.config.id_to_hostname(self.server.hostId)

    def get_host_dest(self):
        host = self.get_host()
        dest = self.config.other_hosts(host)[0]
        assert host != dest
        return host, dest

    def assert_server_alive(self, host):
        self.server.get()
        assert self.server.hostId == self.config.hostname_to_id(host)
        assert self.server.status == 'ACTIVE'
        harness.wait_for_ping(self.ip, duration=30)
        harness.wait_for_ssh(self.shell, duration=30)
        self.breadcrumbs.add('alive on host %s' % host)

    def migrate(self, host, dest):
        log.info('Migrating %s to %s', str(self.server.id), dest)
        self.assert_server_alive(host)
        self.breadcrumbs.add('pre migration to %s' % dest)
        self.client.gcapi.migrate_instance(self.server.id, dest)
        self.assert_server_alive(dest)
        self.breadcrumbs.add('post migration to %s' % dest)

    def fail_migrate(self, host, dest):
        log.info('Expecting Migration %s to %s to fail',
                 str(self.server.id), dest)
        self.breadcrumbs.add('pre expected fail migration to %s' % dest)
        try:
            self.client.gcapi.migrate_instance(self.server.id, dest)
            assert False and 'HttpException expected!'
        except HttpException, e:
            log.debug('Got expected HttpException: %s', str(e))
            assert e.code == 500
        self.assert_server_alive(host)
        self.breadcrumbs.add('post expected fail migration to %s' % dest)

    def test_simple(self):
        host, dest = self.get_host_dest()
        self.migrate(host, dest)
        self.server.delete()

    def test_back_and_forth(self):
        host, dest = self.get_host_dest()
        self.migrate(host, dest)
        self.migrate(dest, host)
        self.migrate(host, dest)
        self.migrate(dest, host)
        self.server.delete()

    def test_dest_ip_address(self):
        host, dest = self.get_host_dest()
        dest_ip = socket.gethostbyaddr(dest)[2][0]
        self.fail_migrate(host, dest_ip)
        self.server.delete()

    def test_dest_does_not_exist(self):
        host = self.get_host()
        dest = 'this-host-does-not-exist'
        self.fail_migrate(host, dest)
        self.server.delete()

    def test_dest_does_not_have_openstack(self):
        host = self.get_host()
        dest = self.config.hosts_without_openstack[0]
        self.fail_migrate(host, dest)
        self.server.delete()

    def test_migrate_self(self):
        host = self.get_host()
        self.fail_migrate(host, host)
        self.server.delete()
