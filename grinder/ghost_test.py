# Copyright 2014 GridCentric Inc.
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

# This module tests some ghost and ghost-policy specific aspects of launch.

from . import harness
from . import requirements

class TestGhostLaunch(harness.TestCase):

    @harness.hosttest
    @harness.requires(requirements.INSTALL_POLICY)
    def test_ghost_clone(self, image_finder):
        with self.harness.blessed(image_finder) as blessed:
            new_policy = \
"""
[*;blessed=%s;*]
unmanaged = false
ghost = true
""" % (blessed.id)
            with self.harness.policy(new_policy):
                flavor_used  = self.harness.nova.flavors.find(
                    name=blessed.image_config.flavor)
                max_pages = flavor_used.ram * 256

                # kick off a single launch, which should bring up a
                # ghost to go with it.
                launched = blessed.launch(paused_on_launch=True)
                target_host = None
                try:
                    vmsctl = launched.vmsctl()
                    generation = vmsctl.generation()
                    target_host = launched.get_host()
                    # turn off eviction to prevent VM unpause
                    vmsctl.clear_flag("eviction.enabled")
                    # check that the plumbing worked and vmsd got a
                    # preshared mem object.
                    ispreshared = vmsctl.get_param("share.preshared")
                    assert str(vmsctl.get_param("share.preshared")) == '1'
                    # check that we've got just the ghost and the launch
                    stats = target_host.get_vmsfs_stats(generation)
                    assert stats['cur_memory_objects'] == 2
                    # check the number of p2m mappings.  because the
                    # ghost is fully mapped and the launch should've
                    # been cloned from the ghost, we should have
                    # exactly 2x the p2m mappings.
                    assert stats['cur_resident'] == (2 * max_pages)
                    # the ghost should still be fully shared and
                    # untouched. The launched clone will have some
                    # dirty pages due to replacements and some runtime
                    # allocation, but most of it should still be
                    # pretty clean and in a shared state.
                    assert stats['cur_shared'] > ((2 * max_pages) *
                                                  self.config.test_sharing_share_ratio)
                    # The actual number of allocated page should be
                    # less than max_pages + dirty.
                    assert stats['cur_allocated'] < (max_pages + stats['cur_dirty'])

                    # let the guest run to make sure it's live.
                    launched.unpause()
                    launched.assert_guest_running()
                finally:
                    if not(self.harness.config.leave_on_failure):
                        if launched:
                            launched.delete()
                        # try to ensure that the ghost gets destroyed
                        # and cleaned up.  At this point the ghost
                        # SHOULD have been made.  If the delete
                        # operation returns an error RC, it means the
                        # ghost didn't get made and that's an error.
                        if target_host:
                            target_host.check_output("vmsctl ghostdel %s" % (generation))
