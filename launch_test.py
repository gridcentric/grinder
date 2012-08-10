import json
import unittest
import logging
import os

import harness

from logger import log
from config import default_config

import pytest

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

    def boot_master(self, image_finder, agent_version=None):
        image_config = image_finder.find(self.client, self.config)
        master = harness.boot(self.client, self.config, image_config)
        breadcrumbs = harness.Breadcrumbs(master)
        breadcrumbs.add('Booted master %s' % master.id)
        setattr(master, 'breadcrumbs', breadcrumbs)
        if agent_version == None:
            agent_version = self.config.agent_version
        # Drop agent package, install it, trivially ensure
        harness.auto_install_agent(master, self.config.agent_version)
        master.breadcrumbs.add("Installed agent version %s" % agent_version)
        harness.check_agent_running(master)
        return master

    def root_command(self, server, cmd, expected_rc = None, expected_stdout = None):
        ssh = harness.SecureRootShell(server)
        if expected_rc is None and expected_stdout is None:
            ssh.check_output(cmd)
        else:
            (rc, _stdout, stderr) = ssh.call(cmd)
            if expected_rc is not None:
                assert rc == expected_rc
            if expected_stdout is not None:
                stdout = [ x.strip('\r') for x  in _stdout.split('\n')[:-1] ]
                assert stdout == expected_stdout
        server.breadcrumbs.add("Root command %s" % str(cmd))

    def drop_caches(self, vm):
        self.root_command(vm, "echo 3 | sudo tee /proc/sys/vm/drop_caches")

    def bless(self, master):
        log.info('Blessing %s', str(master.id))
        master.breadcrumbs.add('Pre bless')
        blessed_list = self.gcapi.bless_instance(master.id)
        assert len(blessed_list) == 1
        blessed = blessed_list[0]
        assert blessed['id'] != master.id

        # Post-essex, the uuid takes the place of the id for instances.
        if self.config.openstack_version == 'diablo':
            assert blessed['uuid'] != master.uuid

        assert str(blessed['metadata']['blessed_from']) == str(master.id)
        assert blessed['name'] != master.name
        assert master.name in blessed['name']
        assert blessed['status'] in ['BUILD', 'BLESSED']
        blessed = harness.get_server(blessed['id'], self.client,
                                     self.config, master.image_config)
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

        # Post-essex, the uuid takes the place of the id for instances.
        if self.config.openstack_version == 'diablo':
            assert launched['uuid'] != blessed.uuid

        assert str(self.client.servers.get(launched['id']).metadata['launched_from']) == str(blessed.id)
        assert launched['name'] != blessed.name
        assert blessed.name in launched['name']
        assert launched['status'] in ['ACTIVE', 'BUILD']

        launched = harness.get_server(launched['id'], self.client, self.config, blessed.image_config)
        harness.wait_while_status(launched, 'BUILD')
        assert launched.status == status
        if status == 'ACTIVE':
            ip = harness.get_addrs(launched)[0]
            harness.wait_for_ping(launched)
            harness.wait_for_ssh(launched)
            breadcrumbs = self.breadcrumb_snapshots[blessed.id].instantiate(launched)
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

    def test_bless_launch(self, image_finder):
        master = self.boot_master(image_finder)

        ### Can't launch master
        e = harness.assert_raises(self.gcapi.exception, self.launch, master)
        assert e.code / 100 == 4 or e.code / 100 == 5

        ### Can't discard master
        e = harness.assert_raises(self.gcapi.exception, self.discard, master)
        assert e.code / 100 == 4 or e.code / 100 == 5

        ### Simple bless and launch
        assert [] == self.list_blessed_ids(master.id)
        blessed_a = self.bless(master)
        assert [blessed_a.id] == self.list_blessed_ids(master.id)

        assert [] == self.list_launched_ids(blessed_a.id)
        launched_a1 = self.launch(blessed_a)
        assert [launched_a1.id] == self.list_launched_ids(blessed_a.id)

        launched_addrs = harness.get_addrs(launched_a1)
        master_addrs = harness.get_addrs(master)
        assert set(launched_addrs).isdisjoint(master_addrs)

        ### Cannot delete blessed
        if self.config.openstack_version == 'diablo':
            # blessed.delete does not fail per se b/c it's nova compute that can't
            # handle the delete of a BLESSED instance. Hence, if nova compute were
            # buggy and did indeed delete the BLESSED instance, then we might not
            # catch it because the buggy deletion races with the launch below.
            blessed_a.delete()
        else:
            # Post-essex, attempting to delete a blessed instance raises a
            # self.gcapi.exception in novaclient.
            e = harness.assert_raises(self.gcapi.exception, blessed_a.delete)
            assert e.code / 100 == 4

        blessed_a.get()
        assert blessed_a.status == 'BLESSED'

        ### Multiple blesses
        blessed_b = self.bless(master)

        blessed_ids = self.list_blessed_ids(master.id)
        assert sorted([blessed_a.id, blessed_b.id]) == sorted(blessed_ids)

        launched_b1 = self.launch(blessed_b)
        assert [launched_a1.id] == self.list_launched_ids(blessed_a.id)
        assert [launched_b1.id] == self.list_launched_ids(blessed_b.id)

        ### Multiple launches
        launched_a2 = self.launch(blessed_a)
        launched_ids = self.list_launched_ids(blessed_a.id)
        assert sorted([launched_a1.id, launched_a2.id]) == sorted(launched_ids)

        ### Delete master before launch
        self.delete(master)
        launched_a3 = self.launch(blessed_a)

        ### Cannot discard blessed with launched
        e = harness.assert_raises(self.gcapi.exception, self.discard, blessed_b)
        assert e.code / 100 == 4 or e.code / 100 == 5
        # Make sure that we can still launch after a failed discard.
        launched_b2 = self.launch(blessed_b)
        self.delete(launched_b1)
        self.delete(launched_b2)
        self.discard(blessed_b)

        ### Clean everything else up
        self.delete(launched_a1)
        self.delete(launched_a2)
        self.delete(launched_a3)
        self.discard(blessed_a)

    def test_launch_iptables_rules(self, image_finder):

        master = self.boot_master(image_finder)

        blessed = self.bless(master)
        launched = self.launch(blessed)

        # The iptables rules applied to the master should also be applied to the launched
        # instance.
        assert harness.get_iptables_rules(master) == harness.get_iptables_rules(launched)

        self.delete(launched)
        assert [] == harness.get_iptables_rules(launched)

        self.discard(blessed)
        self.delete(master)

    def test_list_blessed_launched_bad_id(self, image_finder):
        fake_id = '123412341234'
        assert fake_id not in [s.id for s in self.client.servers.list()]
        assert [] == self.gcapi.list_blessed_instances(fake_id)
        assert [] == self.gcapi.list_launched_instances(fake_id)

    def test_launch_with_target(self, image_finder):
        if self.config.parse_vms_version() < (2, 4):
           pytest.skip('memory target needs vms 2.4 or later')

        master = self.boot_master(image_finder)
        blessed = self.bless(master)

        flavor = self.client.flavors.find(name=self.config.flavor_name)
        flavor_ram = flavor.ram

        def assert_target(target, expected):
            launched = self.launch(blessed, target=target)
            vmsctl = harness.VmsctlInterface(launched, self.config)
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

    def test_launch_with_params(self, image_finder):
        if int(self.config.agent_version) < 1:
            pytest.skip('Need agent version 1 for guest parameters.')

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
        master = self.boot_master(image_finder)

        ip = harness.get_addrs(master)[0]
        master_shell = harness.SecureShell(master)
        master_shell.check_output('cat >> %s' % params_filename, input=params_script)
        master_shell.check_output('chmod +x %s' % params_filename)
        master_shell.check_output('sudo mv %s /etc/gridcentric/clone.d/%s' % (params_filename, params_filename))

        blessed = self.bless(master)

        def assert_guest_params_success(params):
            """ There parameters should successfully be added to the instance. """
            launched = self.launch(blessed, guest_params=params)
            launched_shell = harness.SecureShell(launched)

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

    # Agent tests. We test for installation and dkms variants. We do these on
    # both main distros (Ubuntu and CentOS).
    # We also perform a more thorough test that exercises the introspection
    # functionality of an installed agent. We launch clone/hoard/dropall cycles
    # to get the maximum bang for buck from free page detection. We exercise
    # this cycle on both distros and *all* bitnesses (32 bit, PAE, 64 bit).
    # Hence the parameterization at the bottom.
    @harness.distrotest()
    def test_agent_double_install(self, image_finder):
        master = self.boot_master(image_finder)

        # Reinstall the agent. Shouldn't see any errors.
        harness.auto_install_agent(master, self.config.agent_version)
        master.breadcrumbs.add("Re-installed latest agent")
        harness.check_agent_running(master)

        self.delete(master)

    @harness.distrotest(exclude=['cirros'])
    def test_agent_dkms(self, image_finder):
        if self.config.agent_version == '0':
            pytest.skip("Agent version 0 does not use dkms")

        master = self.boot_master(image_finder)

        # Remove blobs
        self.root_command(master, "rm -f /var/lib/vms/*")
        master.breadcrumbs.add("Removed cached blobs")

        # Now force dkms to sweat
        self.root_command(master, "service vmsagent restart")
        harness.check_agent_running(master)

        # Check a single new blob exists
        self.root_command(master, "ls -1 /var/lib/vms | wc -l", expected_stdout = ['1'])
        # Check that it is good enough even if we kneecap dkms and modules
        self.root_command(master, "rm -f /usr/sbin/dkms /sbin/insmod /sbin/modprobe")
        self.root_command(master, "refresh-vms")
        master.breadcrumbs.add("Recreated kernel blob")

        self.delete(master)

    @harness.distrotest()
    def test_agent_install_remove_install(self, image_finder):
        master = self.boot_master(image_finder)

        # Remove package, ensure its paths are gone
        if master.image_config.distro == 'ubuntu':
            self.root_command(master, "dpkg -r vms-agent")
        elif master.image_config.distro == 'centos':
            self.root_command(master, "rpm -e vms-agent")
        elif master.image_config.distro == 'cirros':
            self.root_command(master, "/etc/init.d/vmsagent stop")
            self.root_command(master, "rm -rf /var/lib/vms")
        self.root_command(master, "stat /var/lib/vms", expected_rc = 1)
        master.breadcrumbs.add("Removed latest agent")

        # Re-install
        harness.auto_install_agent(master, self.config.agent_version)
        master.breadcrumbs.add("Re-installed latest agent")
        harness.check_agent_running(master)

        self.delete(master)

    # There is no good definition for "dropall" has succeeded. However, on
    # a (relatively) freshly booted Linux, fully hoarded, with over 256MiB
    # of RAM, there should be massive removal of free pages. Settle on a
    # 50% threshold for now.
    DROPALL_ACCEPTABLE_FRACTION = 0.5

    # With agent version 1 (or higher) and vms 2.4 (or higher) we can perform a
    # dropall with no need for eviction.paging. With agent version zero or vms
    # 2.3, we cannot perform dropall.
    def __agent_can_dropall(self):
        agent = int(self.config.agent_version)
        (major, minor) = self.config.parse_vms_version()
        return (agent >= 1) and ((major, minor) >= (2, 4))

    # Test agent-0 with vms2.4 and agent-1 with vms2.3
    @harness.archtest()
    def test_cross_agent(self, image_finder):
        if self.__agent_can_dropall():
            agent_version = '0'
        else:
            agent_version = '1'

        master = self.boot_master(image_finder, agent_version=agent_version)

        blessed = self.bless(master)
        launched = self.launch(blessed)

        # VM is not dead...
        self.root_command(launched, "ps aux")
        self.root_command(launched, "find / > /dev/null")

        self.delete(launched)
        self.discard(blessed)
        self.delete(master)

    @harness.archtest()
    @harness.distrotest()
    def test_agent_hoard_dropall(self, image_finder):
        master = self.boot_master(image_finder)

        if self.__agent_can_dropall():
            # Sometimes dkms and depmod will take over a ton of memory in the page
            # cache. Throw that away so it can be freed later by dropall
            self.root_command(master, "echo 3 | sudo tee /proc/sys/vm/drop_caches")

        # We can bless now, and launch a clone
        blessed = self.bless(master)
        launched = self.launch(blessed)

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

        if self.__agent_can_dropall():
            # Now dropall! (agent should help significantly here)
            before = vmsctl.get_current_memory()
            vmsctl.dropall()
            after = vmsctl.get_current_memory()
            assert (float(before)*self.DROPALL_ACCEPTABLE_FRACTION) > float(after)
            log.info("Agent helped to drop %d -> %d pages." % (before, after))

        # VM is not dead...
        self.root_command(launched, "ps aux")
        self.root_command(launched, "find / > /dev/null")

        # Clean up
        self.delete(launched)
        self.discard(blessed)
        self.delete(master)

    # We will launch clones until SHARE_COUNT hit the same host */
    SHARE_COUNT = 2
    # When share-hoarding across a bunch of stopped clones, we expect
    # the resident to allocated ratio to SHARE_RATIO * num of clones
    # i.e. for two clones, 60% more resident than allocated.
    SHARE_RATIO = 0.8

    def test_sharing(self, image_finder):
        # vms 2.3 and earlier don't have per-generation vmsfs stats.
        if self.config.parse_vms_version() < (2, 4):
            pytest.skip("Need vms 2.4 to test sharing")

        master = self.boot_master(image_finder)
        blessed = self.bless(master)

        # Launch until we have SHARE_COUNT clones on one host
        hostdict = {}
        clonelist = []
        while True:
            clone = self.launch(blessed)
            # Surely a simpler way to do this
            vmsctl = harness.VmsctlInterface(clone, self.config)
            clonelist.append((clone, vmsctl))
            host = vmsctl.host
            (hostcount, host_clone_list) = hostdict.get(host, (0, []))
            hostcount += 1
            host_clone_list.append((clone, vmsctl))
            hostdict[host] = (hostcount, host_clone_list)
            if hostcount == self.SHARE_COUNT:
                break

        # Figure out the generation ID
        genid = clonelist[0][1].get_generation()
        for (clone, vmsctl) in clonelist:
            assert vmsctl.get_generation() == genid

        # The last added clone pushed its host to the expected count
        sharinghost = clonelist[-1][1].host
        (hostcount, sharingclones) = hostdict[sharinghost]
        assert hostcount == self.SHARE_COUNT

        # Set all these guys up
        for (clone, vmsctl) in sharingclones:
            vmsctl.pause()
            vmsctl.set_flag("share.enabled")
            vmsctl.set_flag("share.onfetch")
            # We want it to fetch and share zero pages as well. We want the
            # full hoard to complete up to the max footprint. Otherwise our
            # arithmetic below will be borked
            vmsctl.clear_flag("zeros.enabled")
            vmsctl.clear_target()

        # Make them hoard
        for (clone, vmsctl) in sharingclones:
            assert vmsctl.full_hoard()

        # There should be significant sharing going on now
        ssh = harness.HostSecureShell(sharinghost, self.config)
        stats = ssh.get_vmsfs_stats(genid)
        resident = stats['cur_resident']
        allocated = stats['cur_allocated']
        expect_ratio = float(self.SHARE_COUNT) * self.SHARE_RATIO
        real_ratio = float(resident) / float(allocated)
        log.debug("For %d clones on host %s: resident %d allocated %d ratio %f expect %f"
                    % (self.SHARE_COUNT, sharinghost, resident, allocated, real_ratio, expect_ratio))
        assert real_ratio > expect_ratio

        # Release the brakes on the clones and assert some cow happened
        for (clone, vmsctl) in sharingclones:
            vmsctl.unpause()
        stats = ssh.get_vmsfs_stats(genid)
        assert stats['sh_cow'] > 0

        # Get into one clone and cause significant CoW
        (clone, vmsctl) = sharingclones[0]
        # Make room
        self.drop_caches(clone)
        zerofile = os.path.join('/dev/shm/file')
        # Calculate file size, 256 MiB or 90% of the max
        maxmem = vmsctl.get_max_memory()
        target = min(256 * 256, int(0.9 * float(maxmem)))
        # The tmpfs should be allowed to fit the file plus 4MiBs of headroom (inodes and blah)
        tmpfs_size = (target + (256 * 4)) * 4096
        self.root_command(clone, "mount -o remount,size=%d /dev/shm" % (tmpfs_size))
        # And do it
        self.root_command(clone, "dd if=/dev/urandom of=%s bs=4k count=%d" % (zerofile, target))
        stats = ssh.get_vmsfs_stats(genid)
        assert stats['sh_cow'] > target

        # Clean up
        for (clone, vmsctl) in clonelist:
            self.delete(clone)
        self.discard(blessed)
        self.delete(master)
