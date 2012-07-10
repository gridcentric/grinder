import json
import unittest
import logging
import os

from gridcentric.nova.client.exceptions import HttpException

import harness

from logger import log
from config import default_config

if default_config.openstack_version == 'essex':
    from novaclient.exceptions import ClientException

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

def dict_wrapper_list(dict_list):
    return [DictWrapper(d) for d in dict_list]

class TestLaunch(object):

    def setup_method(self, method):
        self.config = default_config
        self.client = harness.create_client(self.config)
        self.gcapi = self.client.gcapi
        self.breadcrumb_snapshots = {}

    def get_vmsctl(self, server):
        """ Returns the VmsctlInfterface for the server """
        osid = server.id
        if self.config.openstack_version == 'diablo':
            osid = server._info['id']
        return harness.VmsctlInterface(str(osid))

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

    def boot_master(self, image = None, has_agent = True):
        conf = self.config
        conf.guest_has_agent = has_agent
        master = harness.boot(self.client, harness.test_name, conf, image)
        ip = harness.get_addrs(master)[0]
        shell = harness.SecureShell(ip, self.config)
        breadcrumbs = harness.Breadcrumbs(shell)
        breadcrumbs.add('Booted master %s' % master.id)
        setattr(master, 'breadcrumbs', breadcrumbs)
        return master

    def root_command(self, master, cmd):
        ip = harness.get_addrs(master)[0]
        ssh = harness.SecureRootShell(ip, self.config)
        (rc, stdout, stderr) = ssh.call(cmd)
        master.breadcrumbs.add("Root command %s" % str(cmd))
        return (rc, stdout, stderr)

    def assert_root_command(self, master, cmd):
        (rc, stdout, stderr) = self.root_command(master, cmd)
        assert rc == 0
         
    def bless(self, master):
        log.info('Blessing %s', str(master.id))
        master.breadcrumbs.add('Pre bless')
        blessed_list = self.gcapi.bless_instance(master.id)
        assert len(blessed_list) == 1
        blessed = blessed_list[0]
        assert blessed['id'] != master.id
        # In essex, the uuid takes the place of the id for instances.
        if self.config.openstack_version != 'essex':
            assert blessed['uuid'] != master.uuid
        assert str(blessed['metadata']['blessed_from']) == str(master.id)
        assert blessed['name'] != master.name
        assert master.name in blessed['name']
        assert blessed['status'] in ['BUILD', 'BLESSED']
        blessed = self.client.servers.get(blessed['id'])
        self.breadcrumb_snapshots[blessed.id] = master.breadcrumbs.snapshot()
        self.wait_for_bless(blessed)
        master.breadcrumbs.add('Post bless, child is %s' % blessed.id)
        return blessed

    def launch(self, blessed, target=None, guest_params=None, status='ACTIVE'):
        log.debug("Launching from %s with target=%s guest_params=%s status=%s"
                  % (blessed.id, target, guest_params, status))
        params = {}
        if target != None:
            params['target'] = target
        if guest_params != None:
            params['guest'] = guest_params
        launched_list = self.gcapi.launch_instance(blessed.id, params=params)

        assert len(launched_list) == 1
        launched = launched_list[0]
        assert launched['id'] != blessed.id

        # In essex, the uuid takes the place of the id for instances.
        if self.config.openstack_version != 'essex':
            assert launched['uuid'] != blessed.uuid

        assert str(self.client.servers.get(launched['id']).metadata['launched_from']) == str(blessed.id)
        assert launched['name'] != blessed.name
        assert blessed.name in launched['name']
        assert launched['status'] in ['ACTIVE', 'BUILD']

        launched = self.client.servers.get(launched['id'])
        harness.wait_while_status(launched, 'BUILD')
        assert launched.status == status
        if status == 'ACTIVE':
            ip = harness.get_addrs(launched)[0]
            harness.wait_for_ping(ip)
            shell = harness.SecureShell(ip, self.config)
            harness.wait_for_ssh(shell)
            breadcrumbs = self.breadcrumb_snapshots[blessed.id].instantiate(shell)
            breadcrumbs.add('Post launch %s' % launched.id)
            setattr(launched, 'breadcrumbs', breadcrumbs)
        return launched

    def list_launched(self, id):
        return dict_wrapper_list(self.gcapi.list_launched_instances(id))

    def list_launched_ids(self, id):
        return [launched.id for launched in self.list_launched(id)]

    def list_blessed(self, id):
        return dict_wrapper_list(self.gcapi.list_blessed_instances(id))

    def list_blessed_ids(self, id):
        return [blessed.id for blessed in self.list_blessed(id)]

    def test_launch_master(self):
        master = self.boot_master()

        e = harness.assert_raises(HttpException, self.launch, master)
        assert e.code == 500

        # Master should still be alive and well at this point.
        master.get()
        assert master.status == 'ACTIVE'
        master.breadcrumbs.add("Alive after launch attempt.")

        self.delete(master)

    def test_discard_master(self):
        master = self.boot_master()

        e = harness.assert_raises(HttpException, self.discard, master)
        assert e.code == 500

        # Master should still be alive and well at this point.
        master.get()
        assert master.status == 'ACTIVE'
        master.breadcrumbs.add("Alive after discard attempt.")

        self.delete(master)

    def test_list_blessed_launched_bad_id(self):
        fake_id = '123412341234'
        assert fake_id not in [s.id for s in self.client.servers.list()]
        assert [] == self.gcapi.list_blessed_instances(fake_id)
        assert [] == self.gcapi.list_launched_instances(fake_id)

    def test_bless_launch(self):
        master = self.boot_master()

        assert [] == self.list_blessed_ids(master.id)
        blessed = self.bless(master)
        assert [blessed.id] == self.list_blessed_ids(master.id)

        assert [] == self.list_launched_ids(blessed.id)
        launched = self.launch(blessed)
        assert [launched.id] == self.list_launched_ids(blessed.id)

        launched_addrs = harness.get_addrs(launched)
        master_addrs = harness.get_addrs(master)
        assert set(launched_addrs).isdisjoint(master_addrs)

        self.delete(launched)
        self.discard(blessed)
        self.delete(master)

    def test_multi_bless(self):
        master = self.boot_master()
        blessed1 = self.bless(master)
        # TODO: This wait_for_bless is necessary because there's a race in
        # blessing when pausing & unpausing qemu. Once we add some
        # synchronization to nova-gc, we can remove this wait_for_bless.
        blessed2 = self.bless(master)

        blessed_ids = self.list_blessed_ids(master.id)
        assert sorted([blessed1.id, blessed2.id]) == sorted(blessed_ids)

        launched1 = self.launch(blessed1)
        launched2 = self.launch(blessed2)

        assert [launched1.id] == self.list_launched_ids(blessed1.id)
        assert [launched2.id] == self.list_launched_ids(blessed2.id)

        self.delete(launched1)
        self.delete(launched2)
        self.delete(master)
        self.discard(blessed1)
        self.discard(blessed2)

    def test_multi_launch(self):
        master = self.boot_master()
        blessed = self.bless(master)
        launched1 = self.launch(blessed)
        launched2 = self.launch(blessed)
        launched_ids = self.list_launched_ids(blessed.id)
        assert sorted([launched1.id, launched2.id]) == sorted(launched_ids)
        self.delete(launched1)
        self.delete(launched2)
        self.discard(blessed)
        self.delete(master)

    def test_delete_master_before_launch(self):
        master = self.boot_master()
        blessed = self.bless(master)
        self.delete(master)
        launched = self.launch(blessed)
        self.delete(launched)
        self.discard(blessed)

    def test_cannot_discard_blessed_with_launched(self):
        master = self.boot_master()
        blessed = self.bless(master)
        launched1 = self.launch(blessed)
        e = harness.assert_raises(HttpException, self.discard, blessed)
        assert e.code == 500
        # Make sure that we can still launch after a failed discard.
        launched2 = self.launch(blessed)
        self.delete(launched1)
        self.delete(launched2)
        self.discard(blessed)
        self.delete(master)

    def test_cannot_delete_blessed(self):
        master = self.boot_master()
        blessed = self.bless(master)
        if self.config.openstack_version == 'essex':
            # In Essex, attempting to delete a blessed instance raises a
            # ClientException in novaclient.
            e = harness.assert_raises(ClientException, blessed.delete)
            assert e.code == 409
        else:
            # blessed.delete does not fail per se b/c it's nova compute that can't
            # handle the delete of a BLESSED instance. Hence, if nova compute were
            # buggy and did indeed delete the BLESSED instance, then we might not
            # catch it because the buggy deletion races with the launch below.
            blessed.delete()

        blessed.get()
        assert blessed.status == 'BLESSED'
        launched = self.launch(blessed)
        self.delete(launched)
        self.discard(blessed)
        self.delete(master)

    def test_launch_with_target(self):

        master = self.boot_master()
        blessed = self.bless(master)

        flavor = self.client.flavors.find(name=self.config.flavor_name)
        flavor_ram = flavor.ram

        def assert_target(target, expected):
            launched = self.launch(blessed, target=target)
            vmsctl = self.get_vmsctl(launched)
            assert expected == vmsctl.get_param("memory.target")
            self.delete(launched)

        assert_target("-1", "0")
        assert_target("0", "0")
        assert_target("1", "1")
        assert_target("%dmb" % (flavor_ram / 2), "%d" % (256 * (flavor_ram / 2)))
        assert_target("%dMB" % (flavor_ram), "%d" % (256 * flavor_ram))
        assert_target("%dMB" % (flavor_ram + 1), "%d" % (256 * (flavor_ram + 1)))
        assert_target("%dGB" % (flavor_ram), "%d" % (262144 * flavor_ram))

        self.discard(blessed)
        self.delete(master)

    def test_launch_with_params(self):

        params_script = """#!/usr/bin/env python
import sys
import json
sys.path.append('/etc/gridcentric/common')
import common
data = common.parse_params()
log = file("/tmp/clone.log", "w")
log.write("%s" % json.dumps(data))
log.flush()
log.close()
"""
        params_filename = "90_clone_params"
        master = self.boot_master()

        ip = harness.get_addrs(master)[0]
        master_shell = harness.SecureShell(ip, self.config)
        master_shell.check_output('cat >> %s' % params_filename, input=params_script)
        master_shell.check_output('chmod +x %s' % params_filename)
        master_shell.check_output('sudo mv %s /etc/gridcentric/clone.d/%s' % (params_filename, params_filename))

        blessed = self.bless(master)

        def assert_guest_params_success(params):
            """ There parameters should successfully be added to the instance. """
            launched = self.launch(blessed, guest_params=params)
            ip = harness.get_addrs(launched)[0]
            launched_shell = harness.SecureShell(ip, self.config)

            stdout, _ = launched_shell.check_output('sudo cat /tmp/clone.log')
            inguest_params = json.loads(stdout)
            for param in params:
                assert param in inguest_params
                assert inguest_params[param] == "verified"
            self.delete(launched)

        def assert_guest_params_failure(params):
            """ There parameters should cause the launching of the instance to fail. """
            launched = self.launch(blessed, guest_params=params, status="ERROR")
            self.delete(launched)

        assert_guest_params_success({})
        assert_guest_params_success({"test_parameter":"verified"})
        assert_guest_params_success({"test_parameter":"verified", "test_parameter2":"verified"})

        assert_guest_params_failure({"sometext": "somelargetext" * 1000})

        self.discard(blessed)
        self.delete(master)

    # There is no good definition for "dropall" has succeeded. However, on
    # a (relatively) freshly booted Linux, fully hoarded, with over 256MiB
    # of RAM, there should be massive removal of free pages. Settle on a
    # 50% threshold for now.
    DROPALL_ACCEPTABLE_FRACTION = 0.5

    def test_agent_hoard_dropall(self, img_distro):
        (image, distro) = img_distro

        master = self.boot_master(image, has_agent = False)

        # Drop package, install it, trivially ensure
        harness.auto_install_agent(master, self.config, distro)
        master.breadcrumbs.add("Installed latest agent")
        self.assert_root_command(master, "ps aux | grep vmsagent | grep -v "\
                                         "grep | grep -v ssh")

        # We can bless now
        assert [] == self.list_blessed_ids(master.id)
        blessed = self.bless(master)
        assert [blessed.id] == self.list_blessed_ids(master.id)

        # And launch a clone
        assert [] == self.list_launched_ids(blessed.id)
        launched = self.launch(blessed)
        assert [launched.id] == self.list_launched_ids(blessed.id)

        launched_addrs = harness.get_addrs(launched)
        master_addrs = harness.get_addrs(master)
        assert set(launched_addrs).isdisjoint(master_addrs)

        # Now let's have some vmsctl fun
        vmsctl = harness.VmsctlInterface(launched, self.config)
        # For a single clone all pages fetched become sharing nominees.
        # We want to drop them anyways since they're not really shared
        vmsctl.set_flag("eviction.dropshared")
        # We want to see the full effect of hoarding, let's not 
        # bypass zeros
        vmsctl.clear_flag("zeros.enabled")
        # Avoid any chance of eviction other than zero dropping
        vmsctl.clear_flag("eviction.paging")
        vmsctl.clear_flag("eviction.sharing")
        # No target so hoard finishes without triggering dropall
        vmsctl.clear_target()
        assert vmsctl.match_expected_params({ "eviction.dropshared"     : 1,
                                              "zeros.enabled"           : 0,
                                              "eviction.paging"         : 0,
                                              "eviction.sharing"        : 0,
                                              "memory.target"           : 0 })

        # Hoard so dropall makes a splash
        assert vmsctl.full_hoard()

        # Now dropall! (agent should help significantly here)
        before = vmsctl.get_current_memory()
        vmsctl.dropall()
        after = vmsctl.get_current_memory()
        assert (float(before)*self.DROPALL_ACCEPTABLE_FRACTION) > float(after)
        log.info("Agent helped to drop %d -> %d pages." % (before, after))

        # VM is not dead...
        self.assert_root_command(launched, "ps aux")
        self.assert_root_command(launched, "find / > /dev/null")

        # Clean up
        self.delete(launched)
        self.discard(blessed)
        self.delete(master)

def pytest_generate_tests(metafunc):
    if "img_distro" in metafunc.funcargnames:
        metafunc.parametrize("img_distro", [("uec-oneiric-server-agent-deps", "ubuntu")], ids=['Oneiric 64bit'])
