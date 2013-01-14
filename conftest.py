import os
import logging
from test.config import default_config, Image
from test.harness import ImageFinder, get_test_distros, get_test_archs
from test.client import create_nova_client
from test.logger import log
from novaclient import exceptions
import ConfigParser

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
    import test.harness
    test.harness.test_name = item.reportinfo()[2]

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
                img = Image(*args, **kwargs)
                log.debug('img: %s' % str(img))
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
        assert default_config.tc_distro != None
        assert default_config.tc_arch != None
        assert default_config.tc_user != None
        try:
            tc_image_ref = config.get('compute', 'image_ref')
            tc_flavor_ref = config.get('compute', 'flavor_ref')
        except ConfigParser.NoSectionError, e:
            log.error('Error parsing %s: %s' % (tempest_config, str(e)))
        except ConfigParser.NoOptionError, e:
            log.error('Error parsing %s: %s' % (tempest_config, str(e)))
        log.debug('tc_image_ref: %s' % tc_image_ref)
        assert tc_image_ref != None and tc_flavor_ref != None
        # Create an image for the parameters obtained from tempest.conf
        client = create_nova_client(default_config)

        # Try to find an image by ID or name.
        try:
            image_details = client.images.find(id=tc_image_ref)
        except exceptions.NotFound:
            image_details = client.images.find(name=tc_image_ref)
        log.debug('Image name: %s' % image_details.name)
        image = Image(image_details.name, default_config.tc_distro, default_config.tc_arch,
            default_config.tc_user)
        log.debug('Appending image %s' % str(image))
        default_config.images.append(image)
        tc_flavor_name = client.flavors.find(id=tc_flavor_ref)
        default_config.flavor_name = tc_flavor_name.name
        log.debug('Flavor used (read from %s): %s' % (tempest_config, tc_flavor_name.name))

        # If the list of hosts is empty, we collect a list of all hosts running service gridcentric.
        if len(default_config.hosts) == 0:
            hosts = client.hosts.list_all()
            for host in hosts:
                log.debug('host %s service %s' % (host.host_name, host.service))
                if host.service == 'gridcentric' and host.host_name not in default_config.hosts:
                    default_config.hosts.append(host.host_name)
            log.debug('host list: %s' % default_config.hosts)
            # If the list of hosts is empty at this point, then we exit because we have no hosts
            # to work with.
            assert len(default_config.hosts) != 0
    default_config.post_config()

def pytest_generate_tests(metafunc):
    if "image_finder" in metafunc.funcargnames:
        ImageFinder.parametrize(metafunc, 'image_finder',
                                get_test_distros(metafunc.function),
                                get_test_archs(metafunc.function))
