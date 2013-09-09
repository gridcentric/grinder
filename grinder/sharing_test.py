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

import pytest
import random
import time
from . import harness
from . import requirements
from . import host
from . logger import log

class TestSharing(harness.TestCase):

    @harness.hosttest
    @harness.requires(requirements.AVAILABILITY_ZONE)
    def test_sharing(self, image_finder):
        with self.harness.booted(image_finder) as master:
            # Allocate a balloon of fixed size before we bless to ensure we'll
            # have a known amount of memory to unshare at our command.
            flavor_used  = self.harness.nova.flavors.find(
                                    name=master.image_config.flavor)
            maxmem_pages = flavor_used.ram * 256
            target_pages = min(256 * 256, int(0.9 * float(maxmem_pages)))

            master.allocate_balloon(target_pages)
            blessed = master.bless()

            clonelist = []
            if not requirements.SCHEDULER_HINTS.check(self.harness.nova):
                target_host_name    = random.choice(self.config.hosts)
                target_host         = host.Host(target_host_name, self.config)
                availability_zone   = target_host.host_az()
                log.debug("Using availability zone capability to target clone "
                          "launching to host %s -> %s." %
                            (target_host_name, availability_zone))

            # It would be nice to call launch() with
            # num_clones=num_sharing_clones.  However, that interface
            # has no guarantee that the clones will all launch on the
            # same host.  That's why this test launches each
            # individually, with code to coerce the scheduler to
            # co-locate the clones.
            generation = None
            for i in range(self.config.test_sharing_sharing_clones):
                if requirements.SCHEDULER_HINTS.check(self.harness.nova):
                    if i == 0:
                        clone               = blessed.launch(paused_on_launch=True)
                        target_host         = clone.get_host()
                        target_host_name    = target_host.id
                        log.debug("Using SameHost scheduling hint to target "
                                  "launching to host %s" % target_host_name)
                    else:
                        clone = blessed.launch(scheduler_hints=
                                                {'same_host':clonelist[0].id},
                                               paused_on_launch=True)
                        assert target_host_name == clone.get_host().id
                else:
                    clone = blessed.launch(availability_zone=availability_zone,
                                           paused_on_launch=True)
                clonelist.append(clone)
                vmsctl = clone.vmsctl()
                vmsctl.set_flag("share.enabled")
                vmsctl.set_flag("share.onfetch")
                vmsctl.clear_flag("zeros.enabled")
                # Turn off eviction to prevent it from unpausing the VM.
                vmsctl.clear_flag("eviction.enabled")
                # Target will be taken care of by full_hoard
                if generation is None:
                    generation = vmsctl.generation()
                else:
                    assert generation == vmsctl.generation()

            # Now that all clones are paused snapshot the stats. Because we
            # don't control when nova tells us the VM is ACTIVE, each clone
            # could have amassed quite a few pages of private memory footprint
            # before we set the knobs right.
            stats           = target_host.get_vmsfs_stats(generation)
            pre_resident    = stats['cur_resident']
            pre_allocated   = stats['cur_allocated']

            # Make them hoard to a full footprint. This will allow us to better
            # see the effect of sharing in the arithmetic below.
            for clone in clonelist:
                vmsctl = clone.vmsctl()
                assert vmsctl.full_hoard()

            # There should be significant sharing going on now.
            stats        = target_host.get_vmsfs_stats(generation)
            resident     = stats['cur_resident'] - pre_resident
            allocated    = stats['cur_allocated'] - pre_allocated
            expect_ratio = float(self.config.test_sharing_sharing_clones) *\
                                 self.config.test_sharing_share_ratio
            real_ratio   = float(resident) / float(allocated)
            log.debug("For %d clones on host %s: resident %d allocated %d "
                      "ratio %f expect %f" %
                        (self.config.test_sharing_sharing_clones, target_host.id,
                            resident, allocated, real_ratio, expect_ratio))
            assert real_ratio > expect_ratio

            # Release the brakes on the clones and assert some unsharing happens.
            for clone in clonelist:
                vmsctl = clone.vmsctl()
                vmsctl.unpause()
                clone.assert_guest_running()
                vmsctl.pause()

            stats = target_host.get_vmsfs_stats(generation)
            assert stats['sh_cow'] > 0

            # Force aggressive unsharing on a single clone.
            clone  = clonelist[0]
            vmsctl = clone.vmsctl()

            # Record the unshare statistics before we begin thrashing the guest
            # with random bytes.
            stats = target_host.get_vmsfs_stats(generation)
            unshare_before_force_cow = stats['sh_cow'] + stats['sh_un']

            vmsctl.unpause()
            time.sleep(1)
            clone.thrash_balloon_memory(target_pages)

            # Figure out the impact of forcing unsharing.
            stats = target_host.get_vmsfs_stats(generation)
            assert (stats['sh_cow'] + stats['sh_un'] - unshare_before_force_cow) > \
                (target_pages - self.config.test_sharing_cow_slack)

            # Clean up.
            for clone in clonelist:
                clone.delete()

            blessed.discard()
