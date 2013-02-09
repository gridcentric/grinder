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

import uuid
import pytest
from uuid import uuid4
import random
import time

from . logger import log
from . config import default_config
from . util import Notifier
from . util import list_filter
from . client import create_client
from . instance import Instance
from . instance import wait_while_status
from . host import Host

# This is set by pytest_runtest_setup in conftest.py.
# This is done prior to each test.
test_name = ''

def boot(client, config, image_config=None, flavor=None):
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
    random.seed(time.time())
    host = random.choice(default_config.hosts)
    host_az = Host(host, config).host_az()
    log.debug('Selected host %s -> %s' % (host, host_az))
    server = client.servers.create(name=name,
                                   image=image.id,
                                   key_name=image_config.key_name,
                                   availability_zone=host_az,
                                   flavor=flavor_id)
    setattr(server, 'image_config', image_config)
    wait_while_status(server, 'BUILD')
    assert server.status == 'ACTIVE'
    assert getattr(server, 'OS-EXT-STS:power_state') == 1

    return server

class ImageFinder(object):

    def __init__(self, skip_on_error=False):
        self.queries = []
        self.skip_on_error = skip_on_error

    def add(self, distro, arch):
        self.queries.append((distro, arch))

    def find(self, client, config):
        for distro, arch in self.queries:
            for image in config.get_images(distro, arch):
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
    def parametrize(metafunc, arg_name, distros, archs, skip_on_error=True):
        finders = []
        ids = []

        for distro in distros:
            for arch in archs:
                finder = ImageFinder(skip_on_error)
                finder.add(distro, arch)
                finders.append(finder)
                ids.append('%s %s' % (distro, arch))

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

def archtest(exclude=None, include=None):
    def _inner(fn):
        archs = list_filter(default_config.get_all_archs(), exclude, include)
        return mark_test(fn, archs=archs)
    return _inner

def get_test_archs(fn):
    return get_test_marker(fn, 'archs', default_config.default_archs)

def distrotest(exclude=None, include=None):
    def _inner(fn):
        distros = list_filter(default_config.get_all_distros(), exclude, include)
        return mark_test(fn, distros=distros)
    return _inner

def get_test_distros(fn):
    return get_test_marker(fn, 'distros', default_config.default_distros)

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
    def __init__(self, harness, name=None):
        self.harness = harness
        self.name = name

    def __enter__(self):
        if self.name == None:
            name = str(uuid4())
        self.secgroup = self.harness.client.security_groups.create(name, 'Created by grinder')
        # Must allow ssh and icmp for further use
        self.harness.client.security_group_rules.create(self.secgroup.id,\
            ip_protocol="tcp", from_port=22, to_port=22, cidr="0.0.0.0/0")
        self.harness.client.security_group_rules.create(self.secgroup.id,\
            ip_protocol="icmp", from_port=-1, to_port=-1, cidr="0.0.0.0/0")
        return self.secgroup

    def __exit__(self, type, value, tb):
        if type == None or not(self.harness.config.leave_on_failure):
            self.harness.client.security_groups.delete(self.secgroup)

class TestHarness(Notifier):
    '''There's one instance of TestHarness per test function that runs.'''
    def __init__(self, config, test_name):
        Notifier.__init__(self)
        self.config = config
        self.test_name = test_name
        (self.client, self.gcapi) = create_client(self.config)

    @Notifier.notify
    def setup(self):
        # Make sure that we have at least one host.
        if len(self.config.hosts) == 0:
            log.error('List of hosts is empty!')
            assert False
        # If we are reading from tempest configuration, tc_distro, tc_arch, and
        # tc_user must be specified.
        if self.config.tempest_config != None:
            if self.config.tc_distro == None:
                log.error('tc_distro must be defined')
                assert False
            if self.config.tc_arch == None:
                log.error('tc_arch must be defined')
                assert False
            if self.config.tc_user == None:
                log.error('tc_user must be defined')
                assert False
            if self.config.tc_image_ref == None:
                log.error('image_ref must be defined')
                assert False
            if self.config.flavor_name == None:
                log.error('flavor_ref must be defined')
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

    @Notifier.notify
    def teardown(self):
        pass

    @Notifier.notify
    def boot(self, image_finder, agent=True, flavor=None):
        image_config = image_finder.find(self.client, self.config)
        server = boot(self.client, self.config, image_config, flavor)
        instance = Instance(self, server, image_config)
        if agent:
            try:
                instance.install_agent()
                instance.assert_agent_running()
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

    def fake_id(self):
        # Generate a fake id (ensure it's fake).
        fake_id = str(uuid.uuid4())
        assert fake_id not in [s.id for s in self.client.servers.list()]
        class FakeServer(object):
            def __init__(self, id):
                self.id = id
        return FakeServer(fake_id)

    def satisfies(self, requirements):
        return all(req.check() for req in requirements)

class TestCase(object):

    harness = None

    def setup_method(self, method):
        self.config = default_config
        self.harness = TestHarness(self.config, test_name)
        self.harness.setup()
        requirements = get_test_marker(method, 'requirements', ())
        if not self.harness.satisfies(requirements):
            pytest.skip('Requirements not met for {}'.format(method.__name__))
        if get_test_marker(method, 'hosttest', False):
            if not(default_config.host_user):
                pytest.skip('Need host user to run %s.' % method.__name__)

    def teardown_method(self, method):
        if self.harness:
            self.harness.teardown()
