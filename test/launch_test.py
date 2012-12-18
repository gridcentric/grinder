import json

from novaclient.exceptions import ClientException

from . import harness
from . logger import log
from . util import assert_raises

PARAMS_SCRIPT = """#!/usr/bin/env python
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

class TestLaunch(harness.TestCase):

    def test_bless(self, image_finder):
        with self.harness.booted(image_finder) as master:
            assert [] == master.list_blessed()
            blessed = master.bless()
            assert blessed.get_status() == 'BLESSED'
            assert [blessed.id] == master.list_blessed()
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
            blessed = master.bless()

            # The iptables rules for the master should also be for launched instances.
            launched = self.launch(blessed)
            master_iptables_rules == launched.get_iptables_rules()

            # Ensure that iptables rules are cleaned up.
            launched.delete()
            assert [] == launched.get_iptables_rules()

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
            params_filename = "90_clone_params"
            master.root_command('cat > %s' % params_filename, input=PARAMS_SCRIPT)
            master.root_command('chmod +x %s' % params_filename)
            master.root_command('mv %s /etc/gridcentric/clone.d/%s' % (params_filename, params_filename))
    
            blessed = master.bless()
    
            def assert_guest_params_success(params):
                """ There parameters should successfully be added to the instance. """
                launched = blessed.launch(guest_params=params)
                (output, error) = launched.root_command('cat /tmp/clone.log')
                inguest_params = json.loads(output)
                for param in params:
                    assert param in inguest_params
                    assert inguest_params[param] == "verified"
                launched.delete()
    
            def assert_guest_params_failure(params):
                """ There parameters should cause the launching of the instance to fail. """
                launched = blessed.launch(guest_params=params, status="ERROR")
                launched.delete()
    
            # Ensure that the guest parameters behave as expected.
            assert_guest_params_success({})
            assert_guest_params_success({"test_parameter":"verified"})
            assert_guest_params_success({"test_parameter":"verified", "test_parameter2":"verified"})
            assert_guest_params_failure({"sometext": "somelargetext" * 1000})
    
            blessed.discard()
