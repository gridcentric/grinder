import os
import socket
import unittest
import time

import harness

from logger import log
from config import default_config

class TestMigration(object):

    def boot_master(self, image_finder):
        self.config = default_config
        self.client = harness.create_client(self.config)
        image_config = image_finder.find(self.client, self.config)
        self.server = harness.boot(self.client, self.config, image_config)
        self.breadcrumbs = harness.Breadcrumbs(self.server)
        self.breadcrumbs.add('booted %s' % self.server.name)
        harness.auto_install_agent(self.server, self.config.agent_version)

    def get_host(self):
        return self.config.id_to_hostname(self.server.tenant_id,
                                          self.server.hostId)

    def get_host_dest(self):
        host = self.get_host()
        dest = self.config.other_hosts(host)[0]
        assert host != dest
        return host, dest

    def wait_while_host(self, host):
        def condition():
            if host != self.config.id_to_hostname(self.server.tenant_id,
                                                  self.server.hostId):
                return True
            self.server.get()
            return False
        harness.wait_for('%s to not be on host %s' % (self.server.id, host),
                         condition)

    def assert_server_alive(self, host):
        self.server.get()
        assert self.server.hostId == \
            self.config.hostname_to_id(self.server.tenant_id, host)
        assert self.server.status == 'ACTIVE'
        harness.wait_for_ping(self.server)
        harness.wait_for_ssh(self.server)
        self.breadcrumbs.add('alive on host %s' % host)

    def migrate(self, host, dest):
        log.info('Migrating %s to %s', str(self.server.id), dest)
        pre_migrate_iptables = harness.get_iptables_rules(self.server, host)
        self.assert_server_alive(host)
        self.breadcrumbs.add('pre migration to %s' % dest)
        self.client.gcapi.migrate_instance(self.server.id, dest)
        self.wait_while_host(host)
        harness.wait_while_status(self.server, 'MIGRATING')
        self.assert_server_alive(dest)
        self.breadcrumbs.add('post migration to %s' % dest)

        # Assert that the iptables rules have been cleaned up.
        assert [] == harness.get_iptables_rules(self.server, host)
        assert pre_migrate_iptables == harness.get_iptables_rules(self.server, dest)

    def fail_migrate(self, host, dest):
        log.info('Expecting Migration %s to %s to fail',
                 str(self.server.id), dest)
        self.breadcrumbs.add('pre expected fail migration to %s' % dest)
        e = harness.assert_raises(self.client.gcapi.exception,
                                  self.client.gcapi.migrate_instance,
                                  self.server.id, dest)
        assert e.code / 100 == 4 or e.code / 100 == 5
        self.assert_server_alive(host)
        self.breadcrumbs.add('post expected fail migration to %s' % dest)

    def test_migration_errors(self, image_finder):
        self.boot_master(image_finder)
        host = self.get_host()

        # Destination does not exist.
        dest = 'this-host-does-not-exist'
        self.fail_migrate(host, dest)

        # Destination does not have openstack.
        dest = self.config.hosts_without_openstack[0]
        self.fail_migrate(host, dest)

        # Cannot migrate to self.
        dest = host
        self.fail_migrate(host, dest)

        # Clean everything up.
        self.server.delete()
        harness.wait_while_exists(self.server)

    def test_back_and_forth(self, image_finder):
        self.boot_master(image_finder)
        host, dest = self.get_host_dest()
        self.migrate(host, dest)
        self.migrate(dest, host)
        self.migrate(host, dest)
        self.migrate(dest, host)
        self.server.delete()
        harness.wait_while_exists(self.server)
