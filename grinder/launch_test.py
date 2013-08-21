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

import uuid
import random
import pytest

from novaclient.exceptions import ClientException, BadRequest

from . import harness
from . logger import log
from . util import assert_raises
from . import requirements
from . import host
from . import instance
from . instance import Instance

class TestLaunch(harness.TestCase):

    def test_bless(self, image_finder):
        with self.harness.booted(image_finder) as master:
            assert [] == master.list_blessed()
            blessed = master.bless()
            assert blessed.get_status() == 'BLESSED'
            assert [blessed.id] == master.list_blessed()
            blessed.discard()

    @harness.requires(requirements.BLESS_NAME)
    def test_bless_with_name(self, image_finder):
        name = 'bless-with-name-{}'.format(uuid.uuid4())
        with self.harness.booted(image_finder) as master:
            blessed = master.bless(name=name)
            # Assertions performed in bless
            blessed.discard()

    def test_launch_one(self, image_finder):
        with self.harness.booted(image_finder) as master:
            # We need the master around to extract addresses.
            blessed = master.bless()

            assert [] == blessed.list_launched()
            launched = blessed.launch()
            assert [launched.id] == blessed.list_launched()

            # Ensure that the addresses are disjoint.
            launched_addrs = launched.get_addrs()
            master_addrs = master.get_addrs()
            assert set(launched_addrs).isdisjoint(master_addrs)

            # Verify that there's no user_data
            launched.assert_userdata('')

            # Cleanup.
            launched.delete()
            blessed.discard()

    @harness.requires(requirements.SECURITY_GROUPS)
    def test_launch_secgroup(self, image_finder):
        with self.harness.security_group() as sg,\
                self.harness.security_group() as unassigned_sg,\
                self.harness.booted(image_finder) as master:
            master.add_security_group(sg.name)

            blessed = master.bless()
            launched = blessed.launch()

            # TODO (tkeith): We are removing security groups rather than
            # querying for them because Essex doesn't support querying.
            # Switch to querying once Essex is no longer supported.

            # Check that security group got passed through from master to
            # launched by removing it
            launched.remove_security_group(sg.name)

            # Try removing a non-assigned security group
            assert_raises(ClientException, launched.remove_security_group, (unassigned_sg.name,))

            # Cleanup.
            launched.delete()
            blessed.discard()

    def test_master_gone(self, image_finder):
        # We do a manual boot to ensure the ordering.
        master = self.harness.boot(image_finder)
        blessed = master.bless()

        # Prior to discard, delete the master.
        master.delete()

        # Launch a VM.
        launched = blessed.launch()

        launched.delete()
        blessed.discard()

    def test_delete_blessed(self, image_finder):
        with self.harness.blessed(image_finder) as blessed:
            e = assert_raises(ClientException, blessed.delete)
            assert e.code / 100 == 4

    def test_multiple_bless(self, image_finder):
        with self.harness.booted(image_finder) as master:
            assert [] == master.list_blessed()
            blessed_a = master.bless()
            assert [blessed_a.id] == master.list_blessed()
            blessed_b = master.bless()
            blessed_ids = master.list_blessed()
            assert sorted([blessed_a.id, blessed_b.id]) == sorted(blessed_ids)
            blessed_a.discard()
            assert [blessed_b.id] == master.list_blessed()
            blessed_b.discard()
            assert [] == master.list_blessed()

    def test_multiple_launch(self, image_finder):
        with self.harness.blessed(image_finder) as blessed:
            assert [] == blessed.list_launched()
            launched_a = blessed.launch()
            assert [launched_a.id] == blessed.list_launched()
            launched_b = blessed.launch()
            launched_ids = blessed.list_launched()
            assert sorted([launched_a.id, launched_b.id]) == sorted(launched_ids)
            launched_a.delete()
            assert [launched_b.id] == blessed.list_launched()
            launched_b.delete()
            assert [] == blessed.list_launched()

    def test_failed_discard(self, image_finder):
        with self.harness.blessed(image_finder) as blessed:
            # Launch a clone.
            launched_a = blessed.launch()

            # Cannot discard blessed with launched.
            e = assert_raises(ClientException, blessed.discard)
            assert e.code / 100 == 4 or e.code / 100 == 5

            # Make sure that we can still launch after a failed discard.
            launched_b = blessed.launch()
            launched_a.delete()
            launched_b.delete()

    def test_launch_iptables_rules(self, image_finder):
        with self.harness.booted(image_finder) as master:
            master_iptables_rules = master.get_iptables_rules()
            assert master_iptables_rules[0]
            assert [] != master_iptables_rules[1]
            blessed = master.bless()

            # The iptables rules for the master should also be for launched instances.
            launched = blessed.launch()
            master_iptables_rules == launched.get_iptables_rules()

            # Remember the host otherwise we won't know where to look after delete.
            host = launched.get_host()

            # Remember the instance's ID before we delete the instance.
            server_id = launched.get_raw_id()

            # Ensure that iptables rules exist before deleting the instance.
            assert launched.get_iptables_rules()[0]
            assert [] != launched.get_iptables_rules()[1]
            launched.delete()

            # Ensure that the rules are cleaned up after deleting the instance.
            assert (False, []) == host.get_nova_compute_instance_filter_rules(server_id)

            # Cleanup the blessed instance.
            blessed.discard()

    def test_launch_master(self, image_finder):
        with self.harness.booted(image_finder) as master:
            # Can't launch master.
            e = assert_raises(ClientException, master.launch)
            assert e.code / 100 == 4 or e.code / 100 == 5

    def test_discard_master(self, image_finder):
        with self.harness.booted(image_finder) as master:
            # Can't discard master.
            e = assert_raises(ClientException, master.discard)
            assert e.code / 100 == 4 or e.code / 100 == 5

    def test_list_blessed_bad_id(self):
        # We should not be able to list blessed instances.
        e = assert_raises(ClientException,
                          self.harness.gcapi.list_blessed_instances,
                          self.harness.fake_id())
        assert e.code / 100 == 4 or e.code / 100 == 5

    def test_list_launched_bad_id(self):
        # Nor launched instances.
        e = assert_raises(ClientException,
                          self.harness.gcapi.list_launched_instances,
                          self.harness.fake_id())
        assert e.code / 100 == 4 or e.code / 100 == 5

    def test_launch_with_params(self, image_finder):
        with self.harness.booted(image_finder) as master:
            blessed = master.bless()

            def assert_guest_params_success(params):
                """ These parameters should successfully be added to the instance. """
                launched = blessed.launch(guest_params=params)
                inguest_params = launched.read_params()
                for param in params:
                    assert param in inguest_params
                    assert inguest_params[param] == "verified"
                launched.delete()

            def assert_guest_params_failure(params):
                """ These parameters should cause the launching of the instance to fail. """
                launched = blessed.launch(guest_params=params, status="ERROR")
                launched.delete()

            # Ensure that the guest parameters behave as expected.
            assert_guest_params_success({})
            assert_guest_params_success({"test_parameter":"verified"})
            assert_guest_params_success({"test_parameter":"verified", "test_parameter2":"verified"})
            assert_guest_params_failure({"sometext": "somelargetext" * 1000})

            blessed.discard()

    @harness.requires(requirements.LAUNCH_NAME)
    def test_launch_with_name(self, image_finder):
        test_name = 'launch-name-{}'.format(str(uuid.uuid4()))
        with self.harness.blessed(image_finder) as blessed:
            launched = blessed.launch(name=test_name)
            # blessed.launch will take care of assertions
            launched.delete()

    @harness.requires(requirements.USER_DATA)
    @harness.platformtest(exclude=["windows"])
    def test_launch_with_user_data(self, image_finder):
        test_data = 'some user data'
        with self.harness.blessed(image_finder) as blessed:
            launched = blessed.launch(user_data=test_data)

            # Verify user_data
            launched.assert_userdata(test_data)

            # Cleanup.
            launched.delete()

    @harness.requires(requirements.SECURITY_GROUPS)
    def test_launch_with_security_group(self, image_finder):
        with self.harness.security_group() as master_sg,\
                 self.harness.security_group() as launched_sg,\
                 self.harness.booted(image_finder) as master:
            master.server.add_security_group(master_sg.name)
            blessed = master.bless()
            launched = blessed.launch(\
                security_groups=[self.config.security_group, launched_sg.name])

            # TODO (tkeith): We are removing security groups rather than
            # querying for them because Essex doesn't support querying.
            # Switch to querying once Essex is no longer supported.

            # Verify that master_sg didn't get passed from master to launched
            assert_raises(ClientException, launched.remove_security_group, (master_sg.name,))

            # Verify that launched_sg was added to launched
            launched.remove_security_group(launched_sg.name)

    def test_repeat_launch_delete(self, image_finder):
        """ This test was added because repeated launching & discarding caused an issue
            setting the IP with DHCP. This test used to fail between the 7th and 16th
            iteration. """
        with self.harness.blessed(image_finder) as blessed:
            for i in range(20):
                launched = blessed.launch()
                launched.delete()

    @harness.requires(requirements.AVAILABILITY_ZONE)
    def test_launch_host_targeted(self, image_finder):
        hosts = self.harness.config.hosts

        def assert_launched_host(blessed, host_name):
            host_az = host.Host(host_name, self.harness.config).host_az()
            launched = blessed.launch(availability_zone=host_az)
            launched.delete()
            # In Grizzly (stock compute and cobalt for compatibility), the
            # az part of an az:host construct is completely ignored!
            if not requirements.SCHEDULER_HINTS.check(self.harness.nova):
                assert_raises(BadRequest, blessed.launch,
                              availability_zone='nonexistent:%s' % host_name)
            assert_raises(BadRequest, blessed.launch,
                          availability_zone='%s:nonexistent' %\
                          self.config.default_az)

        with self.harness.blessed(image_finder) as blessed:
            assert_launched_host(blessed, hosts[0])
            if len(hosts) > 1:
                assert_launched_host(blessed, hosts[1])
            if len(hosts) > 2:
                assert_launched_host(blessed, random.choice(hosts[2:]))

    @harness.requires(requirements.SCHEDULER_HINTS)
    def test_launch_with_bad_hint(self, image_finder):
        with self.harness.blessed(image_finder) as blessed:
            # Ask for a petabyte of free RAM
            assert_raises(BadRequest, blessed.launch,
              scheduler_hints={'query':'[">=","$free_ram_mb",1099511627776]'})

    @harness.requires(requirements.AVAILABILITY_ZONE)
    def test_launch_with_invalid_az(self, image_finder):
        with self.harness.blessed(image_finder) as blessed:
            assert_raises(BadRequest, blessed.launch, availability_zone='nonexistent-az')

    @harness.requires(requirements.AVAILABILITY_ZONE)
    def test_launch_with_az(self, image_finder):
        with self.harness.blessed(image_finder) as blessed:
            launched = blessed.launch(availability_zone=self.config.default_az)
            launched.delete()

    @harness.requires(requirements.NUM_INSTANCES)
    def test_launch_multiple(self, image_finder):
        with self.harness.blessed(image_finder) as blessed:
            for num in [1, 2, 10]:
                launched = blessed.launch(num_instances=num)
                if num != 1:
                    assert num == len(launched)
                else:
                    assert issubclass(launched.__class__, Instance)
                blessed.delete_launched()

    @harness.platformtest(only=["linux"])
    @harness.requires(requirements.LAUNCH_KEY)
    def test_launch_with_key(self, image_finder):
        image_config = image_finder.find(self.harness.nova,
                                         self.harness.config)
        if not image_config.cloudinit:
            pytest.skip('Image does not have cloud-init')
        with self.harness.blessed(image_finder) as blessed:
            with self.harness.keypair() as keypair:
                launched = blessed.launch(keypair=keypair)
                # launch asserts key_name correctness
                launched.delete()

    def test_clones_of_clones(self, image_finder):
        with self.harness.blessed(image_finder) as blessed:
            launched = blessed.launch()
            clones = []
            blessings = []
            for i in range(4):
                clones.append(launched)
                blessed = launched.bless()
                blessings.append(blessed)
                launched = blessed.launch()
            launched.delete()
            # Now delete
            for i in range(4):
                blessed = blessings.pop()
                blessed.discard()
                launched = clones.pop()
                launched.delete()
