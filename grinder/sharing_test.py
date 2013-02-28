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
            flavor_used = self.harness.client.flavors.find(name=master.image_config.flavor)
            maxmem_pages = flavor_used.ram * 256
            target_pages = min(256 * 256, int(0.9 * float(maxmem_pages)))

            master.allocate_balloon(target_pages)
            blessed = master.bless()

            clonelist = []
            target_host_name = random.choice(self.config.hosts)
            target_host = host.Host(target_host_name, self.config)
            availability_zone = target_host.host_az()
            log.debug("Using availability zone capability to target clone "
                      "launching to host %s -> %s." %\
                        (target_host_name, availability_zone))

            generation = None
            for i in range(self.config.test_sharing_sharing_clones):
                clone = blessed.launch(availability_zone = availability_zone)
                clonelist.append(clone)
                vmsctl = clone.vmsctl()
                if generation is None:
                    generation = vmsctl.generation()
                else:
                    assert generation == vmsctl.generation()

            # Set all these guys up.
            for clone in clonelist:
                vmsctl = clone.vmsctl()
                vmsctl.pause()
                vmsctl.set_flag("share.enabled")
                vmsctl.set_flag("share.onfetch")
                vmsctl.clear_flag("zeros.enabled")
                # Eviction and target will be taken care of by full_hoard

            # Make them hoard to a full footprint. This will allow us to better
            # see the effect of sharing in the arithmetic below.
            for clone in clonelist:
                vmsctl = clone.vmsctl()
                assert vmsctl.full_hoard()

            # There should be significant sharing going on now.
            stats = target_host.get_vmsfs_stats(generation)
            resident = stats['cur_resident']
            allocated = stats['cur_allocated']
            expect_ratio = float(self.config.test_sharing_sharing_clones) *\
                                 self.config.test_sharing_share_ratio
            real_ratio = float(resident) / float(allocated)
            log.debug("For %d clones on host %s: resident %d allocated %d ratio %f expect %f"
                        % (self.config.test_sharing_sharing_clones, target_host.id, resident,
                           allocated, real_ratio, expect_ratio))
            assert real_ratio > expect_ratio

            # Release the brakes on the clones and assert some unsharing happens.
            for clone in clonelist:
                vmsctl = clone.vmsctl()
                vmsctl.unpause()
                clone.assert_guest_running()

            stats = target_host.get_vmsfs_stats(generation)
            assert stats['sh_cow'] > 0

            # Pause everyone again, and force aggressive unsharing on a single clone.
            for clone in clonelist:
                vmsctl = clone.vmsctl()
                vmsctl.pause()

            clone = clonelist[0]
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
