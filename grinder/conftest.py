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
from . config import default_config, Image
from . harness import ImageFinder, get_test_distros, get_test_archs
from . client import create_nova_client
from . logger import log
from . requirements import AVAILABILITY_ZONE
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
    from . import harness
    harness.test_name = item.reportinfo()[2]

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
        cfg = ConfigParser.ConfigParser({'image_ref': None,
                                         'username': None,
                                         'flavor_ref': None,
                                         'ssh_user': None,
                                         'username': None,
                                         'password': None,
                                         'tenant_name': None,
                                         'uri': None,
                                         'region': None})
        cfg.read(tempest_config)
        default_config.os_username = cfg.get('compute-admin', 'username')
        default_config.os_password = cfg.get('compute-admin', 'password')
        default_config.os_tenant_name = cfg.get('compute-admin', 'tenant_name')
        default_config.os_auth_url = cfg.get('identity', 'uri')
        default_config.os_region_name = cfg.get('identity', 'region')
        if default_config.os_region_name == '':
            default_config.os_region_name = None

        default_config.tc_user = None
        default_config.tc_user = cfg.get('compute', 'ssh_user')

        client = create_nova_client(default_config)

        default_config.tc_image_ref = cfg.get('compute', 'image_ref')
        default_config.tc_flavor_ref = cfg.get('compute', 'flavor_ref')

        # Create an instance of Image for the parameters obtained from
        # tempest.conf

        # Try to find an image by ID or name.
        try:
            image_details = client.images.find(id=default_config.tc_image_ref)
        except novaclient.exceptions.NotFound:
            try:
                image_details = client.images.find(
                    name=default_config.tc_image_ref)
            except novaclient.exceptions.NotFound, e:
                log.error(str(e))
                image_details = None
        if image_details != None:
            log.debug('Image name: %s' % image_details.name)
            image = Image(image_details.name, default_config.tc_distro,
                          default_config.tc_arch, default_config.tc_user)
            log.debug('Appending image %s' % str(image))
            default_config.images.append(image)
        try:
            tc_flavor = client.flavors.find(id=default_config.tc_flavor_ref)
            default_config.flavor_name = tc_flavor.name
        except novaclient.exceptions.NotFound:
            try:
                tc_flavor = client.flavors.find(
                    name=default_config.tc_flavor_ref)
                default_config.flavor_name = tc_flavor.name
            except novaclient.exceptions.NotFound, e:
                log.error(str(e))
                default_config.flavor_name = None
        log.debug('Flavor used (read from %s): %s' % (tempest_config,
            default_config.flavor_name))

    # We absolutely need the availability zone capability in our extension.
    if not AVAILABILITY_ZONE.check():
        log.error("Please update to version 1.1.1244 of gridcentric_python_novaclient_ext")
        default_config.hosts = []
        return

    # Gather list of hosts: either as defined in pytest.ini or all hosts
    # available.
    try:
        all_hosts = client.hosts.list_all()
        if len(default_config.hosts) == 0:
            hosts = [x.host_name for x in all_hosts]
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
                [x for x in hosts if service not in host_dict.get(x, [])]
            if len(default_config.hosts_without_gridcentric) == 0:
                default_config.hosts_without_gridcentric = [gethostname()]

        default_config.hosts_without_gridcentric = \
            [x for x in default_config.hosts_without_gridcentric if 
                service not in host_dict.get(x, [])]
        default_config.hosts = [x for x in hosts if service in host_dict.get(x,
            [])]

        # Remove duplicates
        default_config.hosts_without_gridcentric =\
            list(set(default_config.hosts_without_gridcentric))
        default_config.hosts = list(set(default_config.hosts))

    except exceptions.AttributeError:
        log.debug('Your version of novaclient does not support HostManager.list_all ')
        log.debug('Please consider updating novaclient')

    log.debug('hosts: %s' % default_config.hosts)
    log.debug('hosts_without_gridcentric: %s' % default_config.hosts_without_gridcentric)

    default_config.post_config()

def pytest_generate_tests(metafunc):
    if "image_finder" in metafunc.funcargnames:
        ImageFinder.parametrize(metafunc, 'image_finder',
                                get_test_distros(metafunc.function),
                                get_test_archs(metafunc.function))
