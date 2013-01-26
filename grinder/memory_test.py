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

from . import harness
from . logger import log

class TestMemory(harness.TestCase):

    @harness.archtest()
    @harness.hosttest
    def test_agent_hoard_dropall(self, image_finder):
        with self.harness.blessed(image_finder) as blessed:
            launched = blessed.launch()

            # This test effectively tests two features: introspection and
            # memory footprint management. Introspection succeeds when we
            # detect as many free pages as desired. Footprint management
            # succeeds when we remove those pages from the actual memory. The
            # latter requires full hoarding of the entire footprint as a
            # precondition, in order to know that we have effectively removed
            # those pages.
            vmsctl = launched.vmsctl()

            vmsctl.set_flag("eviction.dropshared")
            vmsctl.set_flag("stats.enabled")
            vmsctl.clear_flag("zeros.enabled")
            vmsctl.clear_flag("eviction.paging")
            vmsctl.clear_flag("eviction.sharing")

            # No target so hoard finishes without surprises.
            vmsctl.clear_target()
            info = vmsctl.info()
            assert int(info["eviction.dropshared"]) == 1
            assert int(info["zeros.enabled"]) == 0
            assert int(info["eviction.paging"]) == 0
            assert int(info["eviction.sharing"]) == 0
            assert int(info["memory.target"]) == 0
            assert int(info["stats.enabled"]) == 1

            # Hoard...
            assert vmsctl.full_hoard()

            # Make the guest throw away as much memory as possible
            launched.drop_caches()

            # And ... evict everything we can
            vmsctl.set_flag("zeros.enabled")
            vmsctl.dropall()

            # First check the results of introspection
            maxmem = vmsctl.get_max_memory()
            drop_target = float(maxmem) *\
                          self.config.test_memory_dropall_fraction
            freed = vmsctl.get_param("stats.eviction.drop.freepgsize.max")
            assert drop_target < float(freed)
            log.info("Agent helped to drop %d." % int(freed))

            # Now check the results in actual memory footprint
            generation = vmsctl.generation()
            host = vmsctl.instance.get_host()
            stats = host.get_vmsfs_stats(generation)
            freed = int(maxmem) - int(stats["cur_allocated"])
            assert drop_target < float(freed)

            # VM is not dead...
            launched.assert_guest_stable()

            # Clean up.
            launched.delete()

    @harness.archtest(exclude = ["32"])
    @harness.hosttest
    def test_pci_mmio_hole(self, image_finder):
        # Guests capable of addressing RAM over 3GiB will run into
        # the so called PCI MMIO hole from 3GiB to 4GiB. Ensure we
        # handle that correctly. For that to be the case we must
        # tweak the default image flavor to go to >= 4GiB, using
        # the "big ram flavor"
        with self.harness.booted(image_finder, flavor=self.config.big_ram_flavor_name) as master:
            current_flavor =\
                self.harness.client.flavors.find(name = master.image_config.flavor)
            assert current_flavor.ram >= 4096

            # Take over 3.5GiB of ram with random bytes
            master.drop_caches()
            balloon_size_pages = ((3 << 30) + (512 << 20)) >> 12
            fingerprint = master.allocate_balloon(balloon_size_pages)

            # Good to go, bless
            blessed = master.bless()
            launched = blessed.launch()

            # Hoard the clone
            vmsctl = launched.vmsctl()
            vmsctl.clear_flag("zeros.enabled")
            assert vmsctl.full_hoard()
            assert vmsctl.get_current_memory >= balloon_size_pages

            # Compare memory, should match
            launched.assert_balloon_integrity(fingerprint)

            # Clean up
            launched.delete()
            blessed.discard()

