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

    def test_launch_with_target(self, image_finder):
        with self.harness.blessed(image_finder) as blessed:
            # Figure out the nominal ram of this VM.
            ram = blessed.get_ram()

            def assert_target(target, expected):
                launched = blessed.launch(target=target)
                vmsctl = launched.vmsctl()
                assert expected == vmsctl.get_param("memory.target")
                launched.delete()

            # Check that our input targets match.
            assert_target(None, "0")
            assert_target("-1", "0")
            assert_target("0", "0")
            assert_target("1", "1")
            assert_target("%dmb" % (ram / 2), "%d" % (256 * (ram / 2)))
            assert_target("%dMB" % (ram), "%d" % (256 * ram))
            assert_target("%dMB" % (ram + 1), "%d" % (256 * (ram + 1)))
            assert_target("%dGB" % (ram), "%d" % (262144 * ram))

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
            launched.root_command("ps aux")
            launched.root_command("find / > /dev/null")

            # Clean up.
            launched.delete()
