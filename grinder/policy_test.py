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

import sys
import time
import pytest
from datetime import datetime

from . import harness
from . logger import log
from . import requirements
from . import instance
from . util import Background, mb2pages
from . util import timedelta_total_seconds

# For now we only run all policy tests on linux VMs because linux VMs stabilize
# at very small memory footprint after a launch, making it set relatively small
# limits without accounting for the VM's initial memory usage after launch.

class TestPolicy(harness.TestCase):

    @harness.hosttest
    @harness.requires(requirements.INSTALL_POLICY)
    @harness.platformtest(exclude=["windows"])
    def test_memory_limit_enforcement(self, image_finder):
        with self.harness.blessed(image_finder) as blessed:
            memory_limit_mb = 128
            new_policy = \
"""
[*;blessed=%s;*]
memory_limit_mb = %d
unmanaged = false
""" % (blessed.id, memory_limit_mb)

            # Launch a new instance an try to push it's memory above the limit
            # we just set. The memory used should never significantly exceed the
            # memory limit. We expect vmspolicyd to activate eviction during
            # this exercise. This test also ensures that a throttled VM
            # continues to make progress and will eventually complete any memory
            # intensive task (once eviction catches up).
            launched = blessed.launch(paused_on_launch=True)
            vmsctl = launched.vmsctl()
            vmsctl.clear_flag("share.enabled")
            launched.unpause()

            @Background()
            def check_memory_usage(ctl, memory_threshold):
                assert int(ctl.get_param("memory.current")) <= memory_threshold

            with self.harness.policy(new_policy):
                with check_memory_usage(vmsctl, mb2pages(memory_limit_mb) +
                                        self.config.test_policy_headroom_pages):
                    # Allocate memory in the launched VM. Allocate more memory
                    # than the limit set by policy to force eviction.
                    log.info("Calling balloon allocate.")
                    launched.allocate_balloon(int(mb2pages(memory_limit_mb)) * 2)
                    log.info("Done balloon allocate.")

            launched.delete()

    @harness.requires(requirements.INSTALL_POLICY)
    @harness.platformtest(only=["linux"])
    def test_memory_burst_allowed(self, image_finder):
        """ Test that a VM is allowd to burst its memory for a reasonable
        amount of time before being throttled. """
        with self.harness.blessed(image_finder) as blessed:
            memory_limit_mb = 256
            burst_size_mb = 256
            burst_time_ms = 30 * 1000
            update_interval_ms = 5 * 1000 # Set a fairly long update interval so
                                          # we can get multiple samples between
                                          # each update.
            new_policy = \
"""
[*;blessed=%s;*]
memory_limit_mb = %d
burst_size_mb = %d
burst_time_ms = %d
update_interval_ms = %d
unmanaged = false
""" % (blessed.id, memory_limit_mb, burst_size_mb, burst_time_ms,
       update_interval_ms)

            launched = blessed.launch(paused_on_launch=True)
            vmsctl = launched.vmsctl()
            vmsctl.clear_flag("share.enabled")
            launched.unpause()

            # This test ensures a domain is allowed to burst unrestricted for a
            # minimum period of of burst_time_ms. Once this period expires,
            # policyd will attempt to squeeze the domain's memory usage down to
            # it's normal limit. We can ensure the domain has bursted for the
            # minium required period by ensuring we have enough samples from the
            # background thread where the domain was bursting.
            sampling_period_sec = 1.0
            required_bursting_samples = (float(burst_time_ms) / 1000) / \
                sampling_period_sec
            # Allows for a a small inconsistency in the minium samples required.
            required_bursting_samples *= 0.9

            def verify_burst_period(bursting_samples):
                assert bursting_samples >= required_bursting_samples

            @Background(
                interval=sampling_period_sec, verifier=verify_burst_period)
            def ensure_burst(ctl, normal_limit, hard_limit, context=0):
                memory_current = int(ctl.get_param("memory.current"))
                assert memory_current <= hard_limit
                if memory_current > normal_limit:
                    context += 1
                return context

            with self.harness.policy(new_policy):

                # Wait for the domain to accumulate burst credits. Note that
                # domains start at 50% credits.
                time.sleep(float(burst_time_ms + update_interval_ms) / 1000 / 2)

                # We shouldn't be bursting yet.
                assert int(vmsctl.get_param("memory.current")) <= \
                    mb2pages(memory_limit_mb)

                # Start watching for bursts. We need to do this before starting
                # to allocate memory because we don't know how long the full
                # allocation will take. The verifier function will ensure the
                # domain was allowed to burst for the period specified in the
                # policy. We need to ensure the sampling runs for at least the
                # burst period, so if the allocation is completed in less time
                # than the burst period, we need to sleep for the remaining
                # duration.
                with ensure_burst(vmsctl, mb2pages(memory_limit_mb),
                                  mb2pages(memory_limit_mb + burst_size_mb) +
                                           self.config.test_policy_headroom_pages):

                    # Allocate a large balloon which should cause bursting. We
                    # avoid allocating memory right up to the limit to avoid
                    # thrashing. Note that the balloon size needs to take into
                    # account the memory used by the guest to ensure the usage
                    # is in the bursting range but not thrashing. We
                    # empherically found 50% of the burst limit to be the right
                    # balloon size for a barebones linux guest.
                    start_time = datetime.now()
                    launched.allocate_balloon(int(
                        mb2pages(memory_limit_mb + burst_size_mb) * 0.50))
                    alloc_time = timedelta_total_seconds(datetime.now() - start_time)
                    remaining_time = (float(burst_time_ms) / 1000) - alloc_time

                    # Pad the remaining time slightly to avoid clipping samples
                    # at the end of the window (because policyd's resolution is
                    # on the order of update_interval_ms). Waiting longer than
                    # required has no impact on the correctness of the result.
                    remaining_time *= 1.10

                    if remaining_time > 0:
                        log.debug("Waiting %.2f for burst." % remaining_time)
                        time.sleep(remaining_time)

                    # Busy wait until we're no longer allowed to burst.
                    while int(vmsctl.get_param("memory.current")) > \
                            mb2pages(memory_limit_mb):
                        log.debug("Waiting for burst to end.")
                        time.sleep(1.0)

                # Release the balloon and wait for the memory usage to fall
                # under the normal limit. Then ensure that policyd has loosened
                # its grip on the domain to allow it to burst again.
                launched.release_balloon()
                while int(vmsctl.get_param("memory.current")) > \
                        mb2pages(memory_limit_mb):
                    log.debug("Waiting for burst to end after balloon release.")
                    time.sleep(1.0)

                # Assert the limit is set to the burst limit. Allow for slight
                # discrepancy due to policyd rounding.
                # assert int(vmsctl.get_param("memory.limit")) > \
                #     (mb2pages(memory_limit_mb + burst_size_mb) * 0.95)
                while int(vmsctl.get_param("memory.limit")) < \
                        (mb2pages(memory_limit_mb + burst_size_mb) * 0.95):
                    log.debug("Waiting for limit relax.")
                    time.sleep(1.0)

                # Target should be relaxed as well once we've relaxed the limit.
                assert int(vmsctl.get_param("memory.target")) == 0

            launched.delete()
