# Copyright 2011 GridCentric Inc.
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
import logging
from grinder.config import default_config, Image
from grinder.harness import ImageFinder, get_test_distros, get_test_archs
from grinder.client import create_nova_client
from grinder.logger import log
import novaclient
import ConfigParser
from socket import gethostname
import exceptions

def parse_option(value, *default_args, **default_kwargs):
    '''Parses an option value qemu style: comma-separated, optional keys

    Returns tuple (args, kwargs).

    kwargs - dict from key=value options
    args - arguments without '='
    '''
    args = []
    kwargs = {}
    for arg in value.split(','):
        if '=' in arg:
            split = arg.split('=', 1)
            kwargs[split[0]] = split[1]
        else:
            args.append(arg)
    return args, kwargs

def pytest_runtest_setup(item):
    # Can't import harness earlier because pytest screws up importing logger.
    import grinder.harness
    grinder.harness.test_name = item.reportinfo()[2]

def pytest_addoption(parser):
    # Add options for each of the default_config fields.
    for name, value in vars(default_config).iteritems():
        if name == 'images':
            parser.addoption('--image', action="append", type="string",
                             help=Image.__doc__, default=[])
            continue
        else:
            if type(value) == list:
                parser.addoption('--%s' % name, action="store", type="string", default=None,
                                 help='default is %s (comma-separated list)' % str(value))
            elif value == False:
                parser.addoption('--%s' % name, action="store_true",
                                 help='default is false')
            else:
                parser.addoption('--%s' % name, action="store", type="string", default=None,
                                 help='default is %s' % str(value))

def pytest_configure(config):
    for name, value in vars(default_config).iteritems():
        if name == 'images':
            new_value = getattr(config.option, 'image')
            for image in new_value:
                args, kwargs = parse_option(image)
                default_config.images.append(Image(*args, **kwargs))
        else:
            new_value = getattr(config.option, name)
            if new_value != None:
                if type(value) == list:
                    setattr(default_config, name, new_value.split(','))
                else:
                    setattr(default_config, name, new_value)

    level = {'DEBUG': logging.DEBUG,
             'INFO': logging.INFO,
             'WARNING': logging.WARNING,
             'ERROR': logging.ERROR,
             'CRITICAL': logging.CRITICAL}
    loglevel = default_config.log_level.upper() 
    log.setLevel(level.get(loglevel, logging.INFO))

    tempest_config = getattr(config.option, "tempest_config")
    client = create_nova_client(default_config)
    if tempest_config != None:
        # Read parameters from tempest.conf
        config = ConfigParser.ConfigParser({'image_ref': None,
                                            'username': None,
                                            'flavor_ref': None})
        config.read(tempest_config)
        tc_image_ref = None
        tc_flavor_ref = None
        # If we are reading from tempest configuration, tc_distro, tc_arch, and
        # tc_user must be specified.
        if default_config.tc_distro == None:
            log.error('tc_distro must be defined')
            assert False
        if default_config.tc_arch == None:
            log.error('tc_arch must be defined')
            assert False
        if default_config.tc_user == None:
            log.error('tc_user must be defined')
            assert False
        try:
            tc_image_ref = config.get('compute', 'image_ref')
            tc_flavor_ref = config.get('compute', 'flavor_ref')
        except ConfigParser.NoSectionError, e:
            log.error('Error parsing %s: %s' % (tempest_config, str(e)))
            assert False
        except ConfigParser.NoOptionError, e:
            log.error('Error parsing %s: %s' % (tempest_config, str(e)))
            assert False
        log.debug('tc_image_ref: %s' % tc_image_ref)
        if tc_image_ref == None or tc_flavor_ref == None:
            log.error('Both image_ref and flavor_ref must be defined in tempest configuration')
            assert False

        # Create an instance of Image for the parameters obtained from tempest.conf

        # Try to find an image by ID or name.
        try:
            image_details = client.images.find(id=tc_image_ref)
        except novaclient.exceptions.NotFound:
            image_details = client.images.find(name=tc_image_ref)
        log.debug('Image name: %s' % image_details.name)
        image = Image(image_details.name, default_config.tc_distro, default_config.tc_arch,
            default_config.tc_user)
        log.debug('Appending image %s' % str(image))
        default_config.images.append(image)
        tc_flavor_name = client.flavors.find(id=tc_flavor_ref)
        default_config.flavor_name = tc_flavor_name.name
        log.debug('Flavor used (read from %s): %s' % (tempest_config, tc_flavor_name.name))

    # Gather list of hosts: either as defined in pytest.ini or all hosts available.
    try:
        all_hosts = client.hosts.list_all()
        if len(default_config.hosts) == 0:
            hosts = map(lambda x: x.host_name, all_hosts)
        else:
            hosts = default_config.hosts

        log.debug('hosts: %s' % str(hosts))
        # Create a dictionary that maps host name to a list of services.
        host_dict = {}
        for host in all_hosts:
            service_list = host_dict.get(host.host_name, [])
            service_list.append(host.service)
            host_dict[host.host_name] = service_list
            log.debug('host %s service %s' % (host.host_name, host.service))

        service = 'gridcentric'
        if len(default_config.hosts_without_gridcentric) == 0:
            default_config.hosts_without_gridcentric = \
                filter(lambda x: service not in host_dict.get(x, []),
                       hosts)
            if len(default_config.hosts_without_gridcentric) == 0:
                default_config.hosts_without_gridcentric = [gethostname()]
        default_config.hosts_without_gridcentric = \
            filter(lambda x: service not in host_dict.get(x, []),
                   default_config.hosts_without_gridcentric)
        default_config.hosts = filter(lambda x: service in host_dict.get(x, []),
                                      hosts)
    except exceptions.AttributeError:
        log.debug('Your version of novaclient does not support HostManager.list_all ')
        log.debug('Please consider updating novaclient')
        pass

    log.debug('hosts: %s' % default_config.hosts)
    log.debug('hosts_without_gridcentric: %s' % default_config.hosts_without_gridcentric)

    # Make sure that we have at least one host.
    if len(default_config.hosts) == 0:
        log.error('List of hosts is empty!')
        assert False

    default_config.post_config()

def pytest_generate_tests(metafunc):
    if "image_finder" in metafunc.funcargnames:
        ImageFinder.parametrize(metafunc, 'image_finder',
                                get_test_distros(metafunc.function),
                                get_test_archs(metafunc.function))
