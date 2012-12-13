from . import harness
from . logger import log

class TestSharing(harness.TestCase):

    # We will launch clones until SHARE_COUNT hit the same host.
    SHARE_COUNT = 2

    # When share-hoarding across a bunch of stopped clones, we expect
    # the resident to allocated ratio to SHARE_RATIO * num of clones
    # i.e. for two clones, 60% more resident than allocated.
    SHARE_RATIO = 0.8

    @harness.hosttest
    def test_sharing(self, image_finder):
        with self.harness.blessed(image_finder) as blessed:

            # Launch until we have SHARE_COUNT clones on one host.
            hostdict = {}
            clonelist = []

            while True:
                clone = blessed.launch()
    
                # Surely a simpler way to do this.
                clonelist.append(clone)

                # Mark the host the holds this VM.
                host = clone.get_host()
                (hostcount, host_clone_list) = hostdict.get(host.id, (0, []))
                hostcount += 1
                host_clone_list.append(clone)
                hostdict[host.id] = (hostcount, host_clone_list)

                # If we've got enough, break.
                if hostcount == self.SHARE_COUNT:
                    break
   
            # Figure out the generation ID.
            vmsctl = clone.vmsctl()
            generation = vmsctl.generation()
            for clone in clonelist:
                vmsctl = clone.vmsctl()
                assert generation == vmsctl.generation()
   
            # The last host bumped the sharing count.
            (hostcount, sharingclones) = hostdict[host.id]
            assert hostcount == self.SHARE_COUNT
    
            # Set all these guys up.
            for clone in sharingclones:
                vmsctl = clone.vmsctl()
                vmsctl.pause()
                vmsctl.set_flag("share.enabled")
                vmsctl.set_flag("share.onfetch")

                # We want it to fetch and share zero pages as well. We want the
                # full hoard to complete up to the max footprint. Otherwise our
                # arithmetic below will be borked.
                vmsctl.clear_flag("zeros.enabled")
                vmsctl.clear_target()
    
            # Make them hoard.
            for clone in sharingclones:
                vmsctl = clone.vmsctl()
                assert vmsctl.full_hoard()
    
            # There should be significant sharing going on now.
            stats = host.get_vmsfs_stats(generation)
            resident = stats['cur_resident']
            allocated = stats['cur_allocated']
            expect_ratio = float(self.SHARE_COUNT) * self.SHARE_RATIO
            real_ratio = float(resident) / float(allocated)
            log.debug("For %d clones on host %s: resident %d allocated %d ratio %f expect %f"
                        % (self.SHARE_COUNT, str(host), resident,
                           allocated, real_ratio, expect_ratio))
            assert real_ratio > expect_ratio
    
            # Release the brakes on the clones and assert some cow happened.
            for clone in sharingclones:
                vmsctl = clone.vmsctl()
                vmsctl.unpause()
                clone.root_command('uptime')

            stats = host.get_vmsfs_stats(generation)
            assert stats['sh_cow'] > 0
    
            # Pause everyone again to ensure no leaks happen via the sh_un stat.
            for clone in sharingclones:
                vmsctl = clone.vmsctl()
                vmsctl.pause()
    
            # Select the clone we'll be forcing CoW on.
            clone = sharingclones[0]
            vmsctl = clone.vmsctl()
    
            # Calculate file size, 256 MiB or 90% of the max.
            maxmem = vmsctl.get_max_memory()
            target = min(256 * 256, int(0.9 * float(maxmem)))
    
            # Record the CoW statistics before we begin forcing CoW.
            stats = host.get_vmsfs_stats(generation)
            unshare_before_force_cow = stats['sh_cow'] + stats['sh_un']
    
            # Force CoW on our selected clone.
            vmsctl.unpause()
    
            # Make room.
            clone.drop_caches()
    
            # The tmpfs should be allowed to fit the file plus
            # 4MiBs of headroom (inodes and blah).
            tmpfs_size = (target + (256 * 4)) * 4096
            clone.root_command("mount -o remount,size=%d /dev/shm" % (tmpfs_size))
    
            # And do it.
            clone.root_command("dd if=/dev/urandom of=/dev/shm/file bs=4k count=%d" % (target))
    
            # Figure out the impact of forcing CoW.
            stats = host.get_vmsfs_stats(generation)
            assert (stats['sh_cow'] + stats['sh_un'] - unshare_before_force_cow) > target
    
            # Clean up.
            for clone in clonelist:
                clone.delete()
