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
        image_config = image_finder.find(self.harness.nova,
                                         self.harness.config)
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
            info = vmsctl.info()
            assert int(info["eviction.dropshared"]) == 1
            assert int(info["zeros.enabled"]) == 0
            assert int(info["eviction.paging"]) == 0
            assert int(info["eviction.sharing"]) == 0
            assert int(info["stats.enabled"]) == 1

            # Hoard. Will clear target and eviction, remember.
            assert vmsctl.full_hoard()

            # Make the guest throw away as much memory as possible
            launched.drop_caches()

            # And ... evict everything we can
            vmsctl.set_flag("zeros.enabled")
            vmsctl.set_flag("eviction.enabled")
            vmsctl.dropall()

            def conditional_check(cond, image_config):
                if image_config.platform == 'windows':
                    if not cond:
                        return False
                else:
                    assert cond
                return True

            # First check the results of introspection
            maxmem = vmsctl.get_max_memory()
            drop_target = float(maxmem) *\
                          self.config.test_memory_dropall_fraction
            freed = vmsctl.get_param("stats.eviction.drop.freepgsize.max")
            if conditional_check(drop_target < float(freed), image_config):
                log.info("Agent helped to drop %d." % int(freed))
            else:
                log.warn("Agent could only free %d (%d)." %\
                            (int(freed), int(drop_target)))

            # Now check the results in actual memory footprint
            generation = vmsctl.generation()
            host = vmsctl.instance.get_host()
            stats = host.get_vmsfs_stats(generation)
            freed = int(maxmem) - int(stats["cur_allocated"])
            conditional_check(drop_target < float(freed), image_config)

            # VM is not dead...
            launched.assert_guest_stable()

            # Clean up.
            launched.delete()

    @harness.hosttest
    def test_eviction_paging(self, image_finder):
        with self.harness.blessed(image_finder) as blessed:
            # Bring up a fully hoarded clone
            launched = blessed.launch()
            vmsctl = launched.vmsctl()
            vmsctl.clear_flag("zeros.enabled")
            # No sharing
            vmsctl.clear_flag("share.enabled")
            vmsctl.clear_flag("eviction.sharing")
            assert vmsctl.full_hoard()

            # Make the guest allocate a bunch of dirty RAM pages
            launched.drop_caches()
            flavor_used = self.harness.nova.flavors.find(name=launched.image_config.flavor)
            maxmem_pages = flavor_used.ram * 256
            target_pages = min(256 * 256, int(0.9 * float(maxmem_pages)))
            md5 = launched.allocate_balloon(target_pages)

            # And ... evict-page to an arbitrary low watermark
            pageout_pages = target_pages
            vmsctl.set_flag("eviction.dropdirty")
            vmsctl.clear_flag("eviction.dropclean")
            vmsctl.clear_flag("eviction.dropshared")
            vmsctl.set_flag("eviction.paging")
            vmsctl.set_flag("eviction.enabled")
            assert vmsctl.meet_target(pageout_pages)

            # Did we meet the target?
            paged_out = vmsctl.get_param("eviction.pagedout")
            assert paged_out >= pageout_pages

            # Is the VM alive?
            launched.assert_guest_stable()

            # Refill and check
            assert vmsctl.full_hoard()
            launched.assert_balloon_integrity(md5)

            # Clean up.
            launched.delete()
