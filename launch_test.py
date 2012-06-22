import unittest
import logging

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
        self.breadcrumb_snapshots = {}

    def server_breadcrumbs(self, server):
        ip = server.networks.values()[0][0]
        shell = harness.SecureShell(ip, self.config)
        shell = self.server_shell(server)
        return Breadcrum

    def assert_server_alive(self, server):
        server.get()
        assert server.status == 'ACTIVE'
        ip = server.networks.values()[0][0]
        harness.wait_for_ping(ip)
        harness.wait_for_ssh(harness.SecureShell(ip, self.config))

    def wait_for_bless(self, blessed):
        harness.wait_while_status(blessed, 'BUILD')
        assert blessed.status == 'BLESSED'
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

    def wait_for_launch(self, launched):
        harness.wait_while_status(launched, 'BUILD')
        assert launched.status == 'ACTIVE'

    def delete(self, server):
        log.debug('Deleting %s %s', server.name, server.id)
        server.delete()
        harness.wait_while_exists(server)

    def discard(self, server):
        log.debug('Discarding %s %s', server.name, server.id)
        self.gcapi.discard_instance(server.id)
        harness.wait_while_exists(server)

    def boot_master(self):
        master = harness.boot(self.client, harness.test_name, self.config)
        ip = harness.get_addrs(master)[0]
        shell = harness.SecureShell(ip, self.config)
        breadcrumbs = harness.Breadcrumbs(shell)
        breadcrumbs.add('Booted master %s' % master.id)
        setattr(master, 'breadcrumbs', breadcrumbs)
        return master

    def bless(self, master):
        log.info('Blessing %d', master.id)
        master.breadcrumbs.add('Pre bless')
        blessed_list = self.gcapi.bless_instance(master.id)
        assert len(blessed_list) == 1
        blessed = blessed_list[0]
        assert blessed['id'] != master.id
        assert blessed['uuid'] != master.uuid
        assert int(blessed['metadata']['blessed_from']) == master.id
        assert blessed['name'] != master.name
        assert master.name in blessed['name']
        assert blessed['status'] in ['BUILD', 'BLESSED']
        blessed = self.client.servers.get(blessed['id'])
        self.breadcrumb_snapshots[blessed.id] = master.breadcrumbs.snapshot()
        self.wait_for_bless(blessed)
        master.breadcrumbs.add('Post bless, child is %s' % blessed.id)
        return blessed

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
        launched = self.client.servers.get(launched['id'])
        harness.wait_while_status(launched, 'BUILD')
        assert launched.status == 'ACTIVE'
        ip = harness.get_addrs(launched)[0]
        harness.wait_for_ping(ip)
        shell = harness.SecureShell(ip, self.config)
        harness.wait_for_ssh(shell)
        breadcrumbs = self.breadcrumb_snapshots[blessed.id].instantiate(shell)
        breadcrumbs.add('Post launch %s' % launched.id)
        setattr(launched, 'breadcrumbs', breadcrumbs)
        return launched

    def list_blessed(self, id):
        return [DictWrapper(d) for d in self.gcapi.list_blessed_instances(id)]

    def list_blessed_ids(self, id):
        return [blessed.id for blessed in self.list_blessed(id)]

    def test_list_blessed_launched_bad_id(self):
        fake_id = '123412341234'
        assert fake_id not in [s.id for s in self.client.servers.list()]
        assert [] == self.gcapi.list_blessed_instances(fake_id)
        assert [] == self.gcapi.list_launched_instances(fake_id)

    def test_bless_launch(self):
        master = self.boot_master()
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

        # Test launching.
        launched = self.launch(blessed)
        launched_addrs = harness.get_addrs(launched)
        master_addrs = harness.get_addrs(master)
        assert set(launched_addrs).isdisjoint(master_addrs)
        self.assert_server_alive(launched)

        # Can't discard a blessed instance with launched instances:
        try:
            self.discard(blessed)
            assert False and 'HttpException expected!'
        except HttpException, e:
            log.debug('Got expected HttpException: %s', str(e))
            assert e.code == 500
        blessed.get()
        assert blessed.status == 'BLESSED'

        # Discard, wait, then delete.
        self.delete(launched)
        self.discard(blessed)

        self.delete(master)
        # TODO: Test blessing again, test launching more than once, test
        # deleting master then launching.

    def test_multi_bless(self):
        master = self.boot_master()
        blessed1 = self.bless(master)
        # TODO: This wait_for_bless is necessary because there's a race in
        # blessing when pausing & unpausing qemu. Once we add some
        # synchronization to nova-gc, we can remove this wait_for_bless.
        blessed2 = self.bless(master)
        self.assert_server_alive(master)

        blessed_ids = self.list_blessed_ids(master.id)
        assert sorted([blessed1.id, blessed2.id]) == sorted(blessed_ids)
        self.delete(master)
        self.discard(blessed1)
        self.discard(blessed2)

    def test_multi_launch(self):
        master = self.boot_master()
        blessed = self.bless(master)
        launched1 = self.launch(blessed)
        launched2 = self.launch(blessed)
        self.delete(launched1)
        self.delete(launched2)
        self.discard(blessed)
        self.delete(master)

    def test_delete_master(self):
        master = self.boot_master()
        blessed = self.bless(master)
        self.delete(master)
        launched = self.launch(blessed)
        self.delete(launched)
        self.discard(blessed)
