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
from . instance import Ghost
from . instance import Policyd
from . logger import log

class TestGhostLaunch(harness.TestCase):


    @harness.hosttest
    @harness.requires(requirements.INSTALL_POLICY)
    def test_ghost_create(self, image_finder):
        with self.harness.blessed(image_finder) as blessed:
            new_policy = \
"""
[*;blessed=%s;*]
unmanaged = false
ghost = true
""" % (blessed.id)
            with self.harness.policy(new_policy):
                # kick off a single launch, which should bring up a
                # ghost to go with it.
                launched = blessed.launch()
                success = False
                try:
                    vmsctl = launched.vmsctl()
                    generation = vmsctl.generation()
                    log.info('Launched with ghost generation %s', generation)
                    target_host = launched.get_host()
                    # if the policy worked, policyd should have made a
                    # ghost for this launch, and policyd should
                    # succeed in our request to nuke that ghost.
                    ghostid = Policyd.get_ghostid(generation, target_host)
                    log.info('ghost id %d for generation %s', ghostid, generation)
                    # kill the ghost.
                    Ghost.wait_for_death(ghostid, target_host, generation, sendkill=True)
                    # check that policyd untracks it.
                    assert not Policyd.get_ghostid(generation, target_host, must_exist=False)
                    # ghost is dead; no need to try and kill it in finally.
                    ghostid = None
                    # check the domain isn't dead if we yank the ghost.
                    launched.assert_guest_running()

                    success = True
                finally:
                    # the launched instance gets auto-cleaned when the
                    # bless cleans up.
                    if success or not(self.harness.config.leave_on_failure):
                        if ghostid and target_host:
                            # hard kill (via vmstl) the ghost.
                            Ghost.wait_for_death(ghostid, target_host, generation,
                                                 sendkill=True, sendvmsctlkill=True)

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
                success = False
                try:
                    vmsctl = launched.vmsctl()
                    generation = vmsctl.generation()
                    log.info('Launched with ghost generation %s', generation)
                    target_host = launched.get_host()
                    # turn off eviction to prevent VM unpause
                    vmsctl.clear_flag("eviction.enabled")
                    # ensure that a ghost got brought up.
                    ghostid = Policyd.get_ghostid(generation, target_host)
                    log.info('ghost id %d for generation %s', ghostid, generation)
                    # check that the plumbing worked and vmsd got a
                    # preshared mem object.
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

                    success = True
                finally:
                    if not success:
                        if ghostid:
                            stdout, _ = target_host.check_output("vmsctl info %s" % (ghostid),
                                                                 expected_rc = None)
                            log.error('test failed. ghost info: %s', stdout)

                        stdout = vmsctl.call('info')
                        log.error('test failed. launched info: %s', stdout)

                    # the launched instance gets auto-cleaned when the
                    # bless cleans up.
                    if success or not(self.harness.config.leave_on_failure):
                        # try to ensure that the ghost gets destroyed
                        # and cleaned up.  At this point the ghost
                        # SHOULD have been made.  If the delete
                        # operation returns an error RC, it means the
                        # ghost didn't get made and that's an error.
                        if ghostid and target_host:
                            Ghost.wait_for_death(ghostid, target_host, generation,
                                                 sendkill=True, sendvmsctlkill=True)
