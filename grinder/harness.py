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

import os
import uuid
import pytest
import random
from fcntl import flock, LOCK_EX, LOCK_UN
from contextlib import contextmanager

from . logger import log
from . config import default_config
from . util import Notifier
from . util import list_filter
from . util import wait_while_status
from . util import wait_for_status
from . util import wait_while_exists
from . util import install_policy
from . client import create_client
from . instance import InstanceFactory
from . host import Host
from . network import network_name_to_uuid
from . requirements import INSTALL_POLICY

# This is set by pytest_runtest_setup in conftest.py.
# This is done prior to each test.
test_name = ''

def boot(client, network_client, config, image_config=None,
         flavor=None, host=None):
    name = '%s-%s' % (config.run_name, test_name)

    if image_config == None:
        finder = ImageFinder()
        image_config = finder.find(client, config)

    if flavor is None:
        if image_config.flavor is None:
            flavor = config.flavor_name
        else:
            flavor = image_config.flavor
    image_config.flavor = flavor

    flavor_id = client.flavors.find(name=flavor).id

    image = client.images.find(name=image_config.name)

    log.info('Booting %s instance named %s', image.name, name)

    if isinstance(host, Host):
        host_az     = host.host_az()
        hostname    = host.id
    else:
        hostname = random.choice(default_config.hosts)
        host_az  = Host(hostname, config).host_az()
    log.debug('Selected host %s -> %s' % (hostname, host_az))

    if config.network_name is not None:
        network_uuid = network_name_to_uuid(network_client, config.network_name)
        nics = [{'net-id' : network_uuid}]
    else:
        nics = None

    user_data_grinder_UUID = str(uuid.uuid4())
    server = client.servers.create(name=name,
                                   image=image.id,
                                   key_name=image_config.key_name,
                                   # host_az for Folsom and later, ignored in Essex
                                   availability_zone=host_az,
                                   security_groups=[config.security_group],
                                   flavor=flavor_id,
                                   nics=nics,
                                   userdata=user_data_grinder_UUID)
    setattr(server, 'image_config', image_config)
    setattr(server, 'user_data_grinder_UUID', user_data_grinder_UUID)
    wait_while_status(server, 'BUILD')
    assert server.status == 'ACTIVE'
    assert getattr(server, 'OS-EXT-STS:power_state') == 1

    return server

class ImageFinder(object):

    def __init__(self, skip_on_error=False):
        self.queries = []
        self.skip_on_error = skip_on_error

    def add(self, distro, arch, platform):
        self.queries.append((distro, arch, platform))

    def find(self, client, config):
        for distro, arch, platform in self.queries:
            for image in config.get_images(distro, arch, platform):
                try:
                    found = client.images.find(name=image.name)
                    return image
                except Exception:
                    log.warning('Image %s not found, skipping', image.name)
        if self.skip_on_error:
            pytest.skip()
        else:
            raise Exception("No image found.")

    @staticmethod
    def parametrize(metafunc, arg_name, distros, archs, platforms, skip_on_error=True):
        finders = []
        ids = []

        for distro in distros:
            for arch in archs:
                for platform in platforms:
                    finder = ImageFinder(skip_on_error)
                    finder.add(distro, arch, platform)
                    finders.append(finder)
                    ids.append('%s %s %s' % (distro, arch, platform))

        if len(finders) == 0:
            # Append a null ImageFinder if there are no images.
            log.warning('No images found.')
            finders.append(ImageFinder(skip_on_error))
            ids.append('none')

        metafunc.parametrize(arg_name, finders, ids=ids)

def mark_test(fn, **kwargs):
    metadata = getattr(fn, '__test_markers', {})
    metadata.update(kwargs)
    setattr(fn, '__test_markers', metadata)
    return fn

def get_test_marker(fn, marker, default=None):
    return getattr(fn, '__test_markers', {}).get(marker, default)

def archtest(exclude=None, include=None, only=None):
    def _inner(fn):
        archs = list_filter(default_config.get_all_archs(),
                            exclude, include, only)
        return mark_test(fn, archs=archs)
    return _inner

def get_test_archs(fn):
    return get_test_marker(fn, 'archs', default_config.default_archs)

def distrotest(exclude=None, include=None, only=None):
    def _inner(fn):
        distros = list_filter(default_config.get_all_distros(),
                              exclude, include, only)
        return mark_test(fn, distros=distros)
    return _inner

def get_test_distros(fn):
    return get_test_marker(fn, 'distros', default_config.default_distros)

def platformtest(exclude=None, include=None, only=None):
    def _inner(fn):
        platforms = list_filter(default_config.get_all_platforms(),
                                exclude, include, only)
        return mark_test(fn, platforms=platforms)
    return _inner

def get_test_platforms(fn):
    return get_test_marker(fn, 'platforms', default_config.default_platforms)

def hosttest(fn):
    mark_test(fn, hosttest=True)
    return fn

def requires(*requirements):
    def decorator(fn):
        mark_test(fn, requirements=requirements)
        return fn
    return decorator

class BootedInstance:
    def __init__(self, harness, image_finder, agent, **kwargs):
        self.harness = harness
        self.image_finder = image_finder
        self.agent = agent
        self.kwargs = kwargs

    def __enter__(self):
        self.master = self.harness.boot(self.image_finder,
                                        agent=self.agent, **self.kwargs)
        return self.master

    def __exit__(self, type, value, tb):
        if type == None or not(self.harness.config.leave_on_failure):
            self.master.delete(recursive=True)

class BlessedInstance:
    def __init__(self, harness, image_finder, agent, **kwargs):
        self.harness = harness
        self.image_finder = image_finder
        self.agent = agent
        self.kwargs = kwargs

    def __enter__(self):
        self.master = self.harness.boot(self.image_finder,
                                        agent=self.agent, **self.kwargs)
        self.blessed = self.master.bless()
        return self.blessed

    def __exit__(self, type, value, tb):
        if type == None or not(self.harness.config.leave_on_failure):
            self.blessed.discard(recursive=True)
            self.master.delete(recursive=True)

class SecurityGroup:
    def __init__(self, harness):
        self.harness = harness
        self.name = str(uuid.uuid4())

    def __enter__(self):
        self.secgroup = self.harness.nova.security_groups.create(self.name, 'Created by grinder')
        # Must allow ssh, Windows Test Listener, and icmp for further use.
        ssh_port = self.harness.config.ssh_port
        win_port = self.harness.config.windows_link_port
        for port in [ssh_port, win_port]:
            self.harness.nova.security_group_rules.create(self.secgroup.id,\
                ip_protocol="tcp", from_port=port, to_port=port, cidr="0.0.0.0/0")
        self.harness.nova.security_group_rules.create(self.secgroup.id,\
            ip_protocol="icmp", from_port=-1, to_port=-1, cidr="0.0.0.0/0")
        return self.secgroup

    def __exit__(self, type, value, tb):
        if type == None or not(self.harness.config.leave_on_failure):
            self.harness.nova.security_groups.delete(self.secgroup)

class Keypair:
    def __init__(self, harness):
        self.harness = harness
        self.name = str(uuid.uuid4())

    def __enter__(self):
        self.keypair = self.harness.nova.keypairs.create(self.name)
        return self.keypair

    def __exit__(self, type, value, tb):
        if type == None or not(self.harness.config.leave_on_failure):
            self.harness.nova.keypairs.delete(self.keypair)

class Volume:
    def __init__(self, harness, size=None, **kwargs):
        self.harness = harness
        self.name = "grindervol-%s" % str(uuid.uuid4())
        if size is None:
            self.size = 1
        else:
            self.size = size
        self.kwargs = kwargs

    def __enter__(self):
        log.debug("Creating volume %s size %ld kwargs %s" %\
                    (self.name, long(self.size), str(self.kwargs)))
        self.volume = self.harness.cinder.volumes.create(
            self.size, display_name=self.name, **self.kwargs)
        wait_for_status(self.volume, 'available')
        return self.volume

    def __exit__(self, type, value, tb):
        if type == None or not(self.harness.config.leave_on_failure):
            log.debug("Deleting volume %s size %ld kwargs %s" %\
                (self.name, long(self.size), str(self.kwargs)))
            self.volume.delete()
            wait_while_exists(self.volume)

class TestHarness(Notifier):
    '''There's one instance of TestHarness per test function that runs.'''
    def __init__(self, config, test_name):
        Notifier.__init__(self)
        self.config = config
        self.test_name = test_name
        (self.nova, self.gcapi, self.cinder, self.network) =\
                create_client(self.config)
        self.installed_policy = self.config.default_policy

    @Notifier.notify
    def setup(self):
        # Make sure that we have at least one host.
        if len(self.config.hosts) == 0:
            log.error('List of hosts is empty!')
            assert False
        # If we are reading from tempest configuration, tc_distro and tc_arch
        # must be specified.
        if self.config.tempest_config != None:
            if self.config.tc_distro == None:
                log.error('tc_distro must be defined')
                assert False
            if self.config.tc_arch == None:
                log.error('tc_arch must be defined')
                assert False
            if self.config.tc_user == None:
                log.error('tempest [compute] ssh_user must be defined')
                assert False
            if self.config.tc_image_ref == None:
                log.error('tempest [compute] image_ref must be defined')
                assert False
            if self.config.flavor_name == None:
                log.error('tempest [compute] flavor_ref must be defined')
                assert False
        if self.config.os_username == None:
            log.error('os_username must be defined')
            assert False
        if self.config.os_password == None:
            log.error('os_password must be defined')
            assert False
        if self.config.os_tenant_name == None:
            log.error('os_tenant_name must be defined')
            assert False
        if self.config.os_auth_url == None:
            log.error('os_auth_url must be defined')
            assert False

        # Learn policy fp from default config. The default catch-all policy was
        # installed during grinder startup and all custom policies are targetted
        # to specific instances so they shouldn't interfere with any other
        # tests.
        self.policy_lock_fp = self.config.policy_lock_fp

    @Notifier.notify
    def teardown(self):
        pass

    @contextmanager
    def policy(self, policy, extend=True):
        """
        Modifies the vmspolicyd policy on the host. If extend is True,
        the currently defined policy is extended with new policy (new
        policy is prepended) rather than replaced by it.
        """

        if INSTALL_POLICY.check(self.nova):
            # Since we always flock on the same file pointer within a single
            # grinder process, recursive calls to flock will not block. This
            # allows any callers of install_policy to grab the lock around the
            # install_policy() call if they want a large critical section around
            # the policy being installed, without having to worry about
            # deadlocks.
            if extend:
                self.installed_policy += policy
            else:
                self.installed_policy = policy

            flock(self.policy_lock_fp, LOCK_EX)
            try:
                install_policy(self.gcapi, self.installed_policy,
                               self.config.ops_timeout)
                yield
            finally:
                flock(self.policy_lock_fp, LOCK_UN)
        else:
            yield

    @Notifier.notify
    def boot(self, image_finder, agent=True, flavor=None, host=None):
        image_config = image_finder.find(self.nova, self.config)
        server = boot(self.nova, self.network, self.config,
                      image_config, flavor, host)
        instance = InstanceFactory.create(self, server, image_config)
        # ensure the instance is booted, (ping-able and ssh-able for linux)
        instance.wait_for_boot()
        if agent:
            try:
                instance.install_agent()
                instance.post_hook_cloudinit()

            except:
                if not(self.config.leave_on_failure):
                    instance.delete()
                raise
        return instance

    def booted(self, image_finder, agent=True, **kwargs):
        return BootedInstance(self, image_finder, agent, **kwargs)

    def blessed(self, image_finder, agent=True, **kwargs):
        return BlessedInstance(self, image_finder, agent, **kwargs)

    def security_group(self):
        return SecurityGroup(self)

    def keypair(self):
        return Keypair(self)

    def volume(self, size=None, **kwargs):
        return Volume(self, size=size, **kwargs)

    def fake_id(self):
        # Generate a fake id (ensure it's fake).
        fake_id = str(uuid.uuid4())
        assert fake_id not in [s.id for s in self.nova.servers.list()]
        class FakeServer(object):
            def __init__(self, id):
                self.id = id
        return FakeServer(fake_id)

    def satisfies(self, requirements):
        return all(req.check(self.nova) for req in requirements)

class TestCase(object):

    harness = None

    def setup_method(self, method):
        self.config = default_config
        self.harness = TestHarness(self.config, test_name)

        # Early discard truculent image/arch/platform combos
        image_finder = getattr(method, 'image_config', None)
        if image_finder is not None:
            # This will result in a skip
            image_config = image_finder.find(self.harness.nova, self.config)

        self.harness.setup()
        requirements = get_test_marker(method, 'requirements', ())
        if not self.harness.satisfies(requirements):
            pytest.skip('Requirements not met for {0}'.format(method.__name__))
        if get_test_marker(method, 'hosttest', False):
            if not(default_config.host_user):
                pytest.skip('Need host user to run %s.' % method.__name__)

    def teardown_method(self, method):
        if self.harness:
            self.harness.teardown()
