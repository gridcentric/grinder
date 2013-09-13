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
import py.test

from novaclient.exceptions import ClientException, BadRequest

from . import harness
from . logger import log
from . util import assert_raises
from . import requirements
from . host import Host
from . import instance

class TestVolume(harness.TestCase):

    @harness.requires(requirements.VOLUME_SUPPORT)
    @harness.platformtest(exclude=["windows"])
    def test_bless_with_volume(self, image_finder):
        # We call the image finder preemptively to skip building
        # a volume for unworkable combinations
        image_finder.find(self.harness.nova, self.harness.config)
        with self.harness.volume() as volume:
            with self.harness.booted(image_finder) as master:
                device = master.attach_volume(volume)
                md5 = master.prime_volume(device)
                blessed = master.bless()
                master.assert_alive()
                blessed.discard()
                master.verify_volume(device, md5)

    @harness.requires(requirements.VOLUME_SUPPORT)
    @harness.platformtest(exclude=["windows"])
    def test_launch_with_volume(self, image_finder):
        image_finder.find(self.harness.nova, self.harness.config)
        with self.harness.volume() as volume:
            with self.harness.booted(image_finder) as master:
                device = master.attach_volume(volume)
                md5 = master.prime_volume(device)
                blessed = master.bless()
                launched = blessed.launch()
                launched.verify_volume(device, md5)
                master.verify_volume(device, md5)
                launched.delete()
                blessed.discard()

    @harness.requires(requirements.VOLUME_SUPPORT)
    @harness.platformtest(exclude=["windows"])
    def test_launch_with_multiple_volumes(self, image_finder):
        image_finder.find(self.harness.nova, self.harness.config)
        with self.harness.volume() as volume_1:
            with self.harness.volume() as volume_2:
                with self.harness.booted(image_finder) as master:
                    device_1 = master.attach_volume(volume_1)
                    md5_1 = master.prime_volume(device_1)
                    device_2 = master.attach_volume(volume_2)
                    md5_2 = master.prime_volume(device_2)
                    blessed = master.bless()
                    launched = blessed.launch()
                    launched.verify_volume(device_1, md5_1)
                    launched.verify_volume(device_2, md5_2)
                    master.verify_volume(device_1, md5_1)
                    master.verify_volume(device_2, md5_2)
                    launched.delete()
                    blessed.discard()

    @harness.requires(requirements.VOLUME_SUPPORT)
    @harness.platformtest(exclude=["windows"])
    def test_multiple_launch_multiple_volumes(self, image_finder):
        image_finder.find(self.harness.nova, self.harness.config)
        with self.harness.volume() as volume_1:
            with self.harness.volume() as volume_2:
                with self.harness.booted(image_finder) as master:
                    device_1 = master.attach_volume(volume_1)
                    md5_1 = master.prime_volume(device_1)
                    device_2 = master.attach_volume(volume_2)
                    md5_2 = master.prime_volume(device_2)
                    blessed = master.bless()
                    clones = blessed.launch(num_instances=3)
                    for clone in clones:
                        clone.verify_volume(device_1, md5_1)
                        clone.verify_volume(device_2, md5_2)
                    master.verify_volume(device_1, md5_1)
                    master.verify_volume(device_2, md5_2)
                    for clone in clones:
                        clone.delete()
                    blessed.discard()

    @harness.requires(requirements.VOLUME_SUPPORT)
    @harness.platformtest(exclude=["windows"])
    def test_migrate_with_volume(self, image_finder):
        if self.harness.config.skip_migration_tests:
            py.test.skip('Skipping migration tests')
        if len(self.harness.config.hosts) < 2:
            py.test.skip('Need at least 2 hosts to do migration.')
        image_finder.find(self.harness.nova, self.harness.config)
        with self.harness.volume() as volume:
            with self.harness.booted(image_finder) as master:
                device = master.attach_volume(volume)
                md5 = master.prime_volume(device)
                host = master.get_host()
                dest = Host([h for h in self.config.hosts if h != host.id][0], self.harness.config)
                master.migrate(host, dest)
                master.verify_volume(device, md5)

