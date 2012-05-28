import unittest

import harness

from logger import log
from config import default_config

class LaunchTest(unittest.TestCase):

    def setUp(self):
        self.config = default_config
        self.client = harness.create_client()
        self.gcapi = self.client.gcapi

    def assert_server_alive(self, server):
        server.get()
        assert server.status == 'ACTIVE'
        ip = server.networks.values()[0][0]
        harness.wait_for_ping(ip)
        harness.wait_for_ssh(harness.SecureShell(ip), self.config)

    def test_simple(self):
        master = harness.boot(self.client, harness.test_name, self.config)
        assert 0 == len(self.gcapi.list_blessed_instances(master.id))
        log.info('Blessing %s' % str(master.id))
        self.gcapi.bless_instance(master.id)
        blessed_ids = self.gcapi.list_blessed_instances(master.id)
        blessed = self.client.servers.get(blessed_ids[0]['id'])
        harness.wait_while_status(blessed, 'UNKNOWN_STATE')
        assert blessed.status == 'BLESSED'
        self.assert_server_alive(master)

        # need test that servers/status and servers/tail both return BLESSED
        # status
