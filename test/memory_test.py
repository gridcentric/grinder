from . import harness
from . logger import log

class TestMemory(harness.TestCase):

    # There is no good definition for "dropall" has succeeded. However, on
    # a (relatively) freshly booted Linux, fully hoarded, with over 256MiB
    # of RAM, there should be massive removal of free pages. Settle on a
    # 50% threshold for now.
    DROPALL_ACCEPTABLE_FRACTION = 0.5

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
        with self.harness.booted(image_finder) as master:
            # Sometimes dkms and depmod will take over a ton of memory in the page
            # cache. Throw that away so it can be freed later by dropall.
            master.drop_caches()

            # We can bless now, and launch a clone.
            blessed = master.bless()
            launched = blessed.launch()

            # Now let's have some vmsctl fun
            vmsctl = launched.vmsctl()

            # For a single clone all pages fetched become sharing nominees.
            # We want to drop them anyways since they're not really shared.
            vmsctl.set_flag("eviction.dropshared")

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

            # Hoard so dropall makes a splash.
            assert vmsctl.full_hoard()

            # Now dropall! (agent should help significantly here).
            before = vmsctl.get_current_memory()
            vmsctl.dropall()
            after = vmsctl.get_current_memory()
            assert (float(before)*self.DROPALL_ACCEPTABLE_FRACTION) > float(after)
            log.info("Agent helped to drop %d -> %d pages." % (before, after))

            # VM is not dead...
            launched.root_command("ps aux")
            launched.root_command("find / > /dev/null")

            # Clean up.
            launched.delete()
            blessed.discard()
