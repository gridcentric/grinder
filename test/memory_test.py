from . import harness
from . logger import log

class TestMemory(harness.TestCase):

    def test_launch_with_target(self, image_finder):
        with self.harness.blessed(image_finder) as blessed:
            # Figure out the nominal ram of this VM.
            ram = blessed.get_ram()

            def assert_target(target, expected):
                launched = blessed.launch(blessed, target=target)
                vmsctl = launched.vmsctl()
                assert expected == vmsctl.get("memory.target")
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
        # Ensure no parameter bogosity
        self.config.dropall_acceptable_fraction =\
            float(self.config.dropall_acceptable_fraction)

        with self.harness.blessed(image_finder) as blessed:
            launched = blessed.launch()

            # This test effectively tests two features: introspection and
            # memory footprint management. We do not need to hoard, or to tweak
            # flags in order to test introspection: the count of free pages
            # will be computed correctly regardless (we do need to drop caches
            # in order to have many free pages). For the footprint management
            # to work, we need to first enable zeros, in order to fetch zero
            # pages during hoard. And then we need to re-enable zeros, in order
            # to drop free pages during dropall.

            # Now let's have some vmsctl fun
            vmsctl = launched.vmsctl()

            # For a single clone all pages fetched become sharing nominees.
            # We want to drop them anyways since they're not really shared.
            vmsctl.set_flag("eviction.dropshared")

            # We will use stats output to verify functionality
            vmsctl.set_flag("stats.enabled")

            # We want to see the full effect of hoarding, let's not bypass zeros.
            vmsctl.clear_flag("zeros.enabled")

            # Avoid any chance of eviction other than zero dropping.
            vmsctl.clear_flag("eviction.paging")
            vmsctl.clear_flag("eviction.sharing")

            # No target so hoard finishes without triggering dropall.
            vmsctl.clear_target()
            info = vmsctl.info()
            assert int(info["eviction.dropshared"]) == 1
            assert int(info["zeros.enabled"]) == 0
            assert int(info["eviction.paging"]) == 0
            assert int(info["eviction.sharing"]) == 0
            assert int(info["memory.target"]) == 0
            assert int(info["stats.enabled"]) == 1

            # Hoard so dropall makes a splash.
            assert vmsctl.full_hoard()

            # Sometimes dkms and depmod will take over a ton of memory in the page
            # cache. Throw that away so it can be freed later by dropall.
            launched.drop_caches()

            # We hypocritically turn zeros back on. Otherwise they won't really
            # be dropped. This is a test after all.
            vmsctl.set_flag("zeros.enabled")

            # Now dropall! (agent should help significantly here).
            vmsctl.dropall()

            # First check the results of introspection
            maxmem = vmsctl.get_max_memory()
            drop_target = float(maxmem) * self.config.dropall_acceptable_fraction
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
