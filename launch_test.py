import unittest

from gridcentric.nova.client.exceptions import HttpException

import harness

from logger import log
from config import default_config

class DictWrapper(object):
    def __init__(self, d):
        self.d = d
        for k, v in d.items():
            if isinstance(v, dict):
                v = DictWrapper(v)
            elif isinstance(v, list):
                v = [DictWrapper(i) for i in v]
            setattr(self, k, v)

    def __str__(self):
        return str(self.d)

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
        harness.wait_for_ssh(harness.SecureShell(ip, self.config))

    def wait_for_bless(self, blessed):
        harness.wait_while_status(blessed, 'BUILD')
        assert blessed.status == 'BLESSED'

    def wait_for_launch(self, launched):
        harness.wait_while_status(launched, 'BUILD')
        assert launched.status == 'ACTIVE'

    def bless(self, master):
        log.info('Blessing %d', master.id)
        blessed_list = self.gcapi.bless_instance(master.id)
        assert len(blessed_list) == 1
        blessed = blessed_list[0]
        assert blessed['id'] != master.id
        assert blessed['uuid'] != master.uuid
        assert int(blessed['metadata']['blessed_from']) == master.id
        assert blessed['name'] != master.name
        assert master.name in blessed['name']
        assert blessed['status'] in ['BUILD', 'BLESSED']
        return self.client.servers.get(blessed['id'])

    def launch(self, blessed):
        launched_list = self.gcapi.launch_instance(blessed.id)
        assert len(launched_list) == 1
        launched = launched_list[0]
        assert launched['id'] != blessed.id
        assert launched['uuid'] != blessed.uuid
        # TODO: Enable this assert once issue #179 is fixed.
        # assert int(launched['metadata']['launched_from']) == blessed.id
        assert int(self.client.servers.get(launched['id']).metadata['launched_from']) == blessed.id
        assert launched['name'] != blessed.name
        assert blessed.name in launched['name']
        assert launched['status'] in ['ACTIVE', 'BUILD']
        return self.client.servers.get(launched['id'])

    def list_blessed(self, id):
        return [DictWrapper(d) for d in self.gcapi.list_blessed_instances(id)]

    def test_list_blessed_launched_bad_id(self):
        fake_id = '123412341234'
        assert fake_id not in [s.id for s in self.client.servers.list()]
        assert [] == self.gcapi.list_blessed_instances(fake_id)
        assert [] == self.gcapi.list_launched_instances(fake_id)

    def test_bless_launch(self):
        master = harness.boot(self.client, harness.test_name, self.config)
        assert [] == self.gcapi.list_blessed_instances(master.id)

        blessed = self.bless(master)

        # Test list_blessed
        blessed_list = self.list_blessed(master.id)
        assert len(blessed_list) == 1
        assert blessed_list[0].id == blessed.id

        # Wait for the bless to complete. Once complete, the master should be
        # active again.
        self.wait_for_bless(blessed)
        self.assert_server_alive(master)

        # Test issue #152. The severs/detail and servers/<ID> were returning
        # difference statuses for blessed servers. servers.get() retrieves
        # servers/<ID> and servers.list() retrieves servers/detail.
        self.client.servers.get(blessed.id).status == 'BLESSED'
        for server in self.client.servers.list():
            if server.id == blessed.id:
                assert server.status == 'BLESSED'
                break
        else:
            assert False

        # Test launching.
        launched = self.launch(blessed)
        self.wait_for_launch(launched)
        launched_addrs = harness.get_addrs(launched)
        master_addrs = harness.get_addrs(master)
        assert set(launched_addrs).isdisjoint(master_addrs)
        self.assert_server_alive(launched)

        # Can't discard a blessed instance with launched instances:
        try:
            self.gcapi.discard_instance(blessed.id)
            assert False and 'HttpException expected!'
        except HttpException, e:
            log.debug('Got expected HttpException: %s', str(e))
            assert e.code == 500
        blessed.get()
        assert blessed.status == 'BLESSED'

        # Discard, wait, then delete.
        launched.delete()
        harness.wait_while_exists(launched)
        self.gcapi.discard_instance(blessed.id)
        harness.wait_while_exists(blessed)

        master.delete()
        # TODO: Test blessing again, test launching more than once, test
        # deleting master then launching.
