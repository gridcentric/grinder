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

from . logger import log

import inspect
import os
import hashlib
import time
import random

from getpass import getuser
from socket import gethostname

DEFAULT_KEY_PATH = os.path.join(os.getenv('HOME'), '.ssh', 'id_rsa')
DEFAULT_DROPALL_FRACTION    = 0.5
DEFAULT_SHARING_CLONES      = 2
DEFAULT_SHARE_RATIO         = 0.8
DEFAULT_COW_SLACK           = 1500

class Image(object):
    '''Add an image.
Fields are specified with comma-separated key=val pairs:
name -- the name of the image in glance,
distro -- the linux distribution,
arch -- the architecture,
user -- the user to login as,
key_path -- the path to the SSH key for the user,
key_name -- the name of the key for booting.
flavor -- the flavor to use to boot this image, overrides the global 
          default config.flavor_name.
e.g. --image 11.10-a1-64,distro=ubuntu,user=ubuntu,arch=64
'''
    def __init__(self, name, distro, arch, user='root', key_path=None,
                 key_name=None, flavor=None):
        self.name = name
        self.distro = distro
        self.arch = arch
        self.user = user
        self.key_path = key_path
        self.key_name = key_name
        self.flavor = flavor

    def check(self):
        assert self.distro
        assert self.arch
        assert self.user
        assert self.key_path

    def __repr__(self):
        return 'Image(name=%s, distro=%s, ' % (self.name, self.distro) + \
            'arch=%s, user=%s, ' % (self.arch, self.user) + \
            'key_path=%s, key_name=%s, flavor=%s)' % \
                (self.key_path, self.key_name, self.flavor)

class Config(object):

    def __init__(self):
        # Hosts in the OpenStack cluster. These are automatically
        # inferred in most cases, see Readme.md.
        self.hosts = []

        # Hosts without the Gridcentric service installed. There should be at
        # least one for the benefit of the test_migration_errors test.
        # Otherwise, the test is skipped.
        self.hosts_without_gridcentric = []

        # Security group for all testing instanced
        self.security_group = 'default'

        # Instance flavor; determines RAM and what disks are attached.
        self.flavor_name = 'm1.tiny'

        # Some tests require instances with >= 4GiB of RAM
        self.big_ram_flavor_name = "m1.medium"

        # Name of the key to inject into the instances. You may use either
        # this mechanism to inject a guest key, or save some images with a
        # key preprovisioned. Both are acceptable.
        self.guest_key_name = None

        # The default path for the counter-part private key that is injected
        # into guests. We require logging into guests as part of the tests.
        self.guest_key_path = DEFAULT_KEY_PATH

        # Some tests will ssh to the hosts and ensure that the state is as
        # expected. This will happen using the host_user and the private key
        # behind host_key_path below.
        self.host_user = None
        self.host_key_path = DEFAULT_KEY_PATH

        # How long to wait for servers to come up, become ping-able, ssh-able,
        # etc. In seconds.
        self.ops_timeout = 600

        # A custom agent location (passed to the gc-install-agent command).
        self.agent_location = None
        self.agent_version  = 'latest'

        # The arch to use for non-arch tests (i.e., tests that aren't sensitive
        # to the arch).
        self.default_archs = []

        # The distro to use for non-distro tests (i.e., tests that aren't
        # sensitive to the distro).
        self.default_distros = []

        # Name to prefix to all of the tests. Defaults to the environment
        # variable RUN_NAME if available, otherwise one is constructed from
        # the current host, user and pid.
        self.run_name = None

        # The images available in Glance for the tests to use. The tests need
        # images of certain distributions for certain architectures; hence the
        # image names aren't important. See Image.
        # 
        # We no longer store defaults here in this repo, but as an example:
        #   Image('cirros-0.3.0-x86_64', distro='cirros', arch='64', user='cirros'),
        #   Image('oneiric-agent-ready', distro='ubuntu', arch='64', user='ubuntu'),
        #   Image('precise-32-agent-ready', distro='ubuntu', arch='32', user='root'),
        #   Image('precise-pae-agent-ready', distro='ubuntu', arch='pae', user='root'),
        #   Image('centos-6.3-64-agent-ready', distro='centos', arch='64', user='root'),
        #   Image('centos-6.3-32-agent-ready', distro='centos', arch='32', user='root'),
        #   Image('centos-6.3-pae-agent-ready', distro='centos', arch='pae', user='root'),
        #   Image('windows7-64bit-virtio', distro='windows', arch='64', user='root', flavor='m1.medium')
        self.images = []

        # Whether to leave the VMs around on failure.
        self.leave_on_failure = False

        # Parameters for reading test configuration from a Tempest configuration file:
        #   tempest_config is the path of the configuration file
        #   tc_distro is the distro for the default guest image
        #   tc_arch is the arch for the default guest image
        # The function pytest_configure will use these parameters to construct
        # one instance of Image 
        # (e.g. Image('precise-32-agent-ready', distro='ubuntu', arch='32', user='root'))
        self.tempest_config = None
        self.tc_distro = None
        self.tc_arch = None

        # Authentication parameters
        self.os_username = os.environ.get('OS_USERNAME')
        self.os_password = os.environ.get('OS_PASSWORD')
        self.os_tenant_name = os.environ.get('OS_TENANT_NAME')
        self.os_auth_url = os.environ.get('OS_AUTH_URL')
        self.os_region_name = os.environ.get('OS_REGION_NAME', 'RegionOne')

        # Folsom and later: a default availability zone that contains testing hosts
        self.default_az = 'nova'

        # Parameter for the memory-hoard-dropall test. Only change if you
        # really know what you are doing. There is no good definition for
        # the "success" of a memory eviction operation. However, on a
        # (relatively) freshly booted Linux, fully hoarded, with over 256MiB of
        # RAM, there should be massive removal of free pages. Settle on a 50%
        # threshold by default.
        self.test_memory_dropall_fraction = DEFAULT_DROPALL_FRACTION

        # These are knobs that control the sharing test, and you should be very
        # sure about what you are doing before changing them.
        # Number of clones that will share memory.
        self.test_sharing_sharing_clones = DEFAULT_SHARING_CLONES

        # When share-hoarding across a bunch of stopped clones, we expect
        # the resident to allocated ratio to be test_sharing_share_ratio * num
        # of clones i.e. for two clones, 60% more resident than allocated.
        self.test_sharing_share_ratio = DEFAULT_SHARE_RATIO

        # We cannot avoid a small but unknown amount of CoW to happen before we
        # start accounting. So provide a slack to absorb that unknown number of
        # pages and prevent spurious failures.
        self.test_sharing_cow_slack = DEFAULT_COW_SLACK

        # Self explanatory
        self.skip_migration_tests = False

        # Test output spews endless 'DEBUG' API calls when logging level is set
        # to 'DEBUG'. Control what logging levels we want to see.
        self.log_level = 'INFO'

        # Set this flag on the command line to see HTTP request/response to nova API.
        self.http_log_debug = False

    def get_all_archs(self):
        return list(set([i.arch for i in self.images]))

    def get_all_distros(self):
        return list(set([i.distro for i in self.images]))

    def post_config(self):
        if self.run_name == None:
            if os.getenv('RUN_NAME'):
                self.run_name = os.getenv('RUN_NAME')
            else:
                pid = os.getpid()
                ppid = os.getppid()
                user = getuser()
                host = gethostname()
                self.run_name = '%s@%s-%d-%d' % (user, host, ppid, pid)

        archs = []
        distros = []
        for image in self.images:
            if not(image.arch) in archs:
                archs.append(image.arch)
            if not(image.distro) in distros:
                distros.append(image.distro)
            if image.key_name == None:
                image.key_name = self.guest_key_name
            if image.key_path == None:
                image.key_path = self.guest_key_path
        if len(self.default_archs) == 0:
            self.default_archs = archs
        if len(self.default_distros) == 0:
            self.default_distros = distros

        # Cast number options, handle bogosity
        def handle_number_option(opt, type, name, default, min, max):
            try:
                opt = type(opt)
            except ValueError:
                log.warn("Bad value for %s, back to default %s" %
                            (name, str(default)))
                opt = default
            if opt < min or opt > max:
                log.warn("Provided %s %s will break the test, back to "
                         "default %s." % (name, str(opt), str(default)))
                opt = default
            return opt

        random.seed(time.time())

        self.test_sharing_sharing_clones =\
            handle_number_option(self.test_sharing_sharing_clones,
                                 int, "sharing clones",
                                 DEFAULT_SHARING_CLONES, 2, 10)
        self.test_sharing_share_ratio =\
            handle_number_option(self.test_sharing_share_ratio,
                                 float, "sharing ratio",
                                 DEFAULT_SHARE_RATIO, 0.25, 0.99)
        self.test_sharing_cow_slack =\
            handle_number_option(self.test_sharing_cow_slack,
                                 int, "sharing cow slack",
                                 DEFAULT_COW_SLACK, 0, 16 * 256)
        self.test_memory_dropall_fraction =\
            handle_number_option(self.test_memory_dropall_fraction,
                                 float, "dropall fraction",
                                 DEFAULT_DROPALL_FRACTION, 0.25, 0.99)

    def get_images(self, distro, arch):
        return filter(lambda i: i.distro == distro and i.arch == arch, self.images)

    def hostname_to_ids(self, tenant_id, hostname):
        essex_hash  = hashlib.sha224(str(tenant_id) + str(hostname)).hexdigest()
        diablo_hash = hashlib.sha224(str(hostname)).hexdigest()
        print "hostname hashes for %s" % hostname
        print "essex = %s" % essex_hash
        print "diablo = %s" % diablo_hash
        return [essex_hash, diablo_hash]

    def id_to_hostname(self, tenant_id, host_id):
        for hostname in self.hosts:
            if host_id in self.hostname_to_ids(tenant_id, hostname):
                return hostname
        raise KeyError(host_id)

default_config = Config()
