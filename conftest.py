from config import default_config, Image

from harness import ImageFinder, get_test_distros, get_test_archs

import os

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
    import harness
    harness.test_name = item.reportinfo()[2]

def pytest_addoption(parser):
    # Add options for each of the default_config fields.
    for name, value in vars(default_config).iteritems():
        if name == 'images':
            continue
        if type(value) == list:
            help='default is %s (comma-separated list)' % ','.join(value)
        else:
            help='default is %s' % value
        parser.addoption('--%s' % name, action="store", type="string",
                         default=None, help=help)
    parser.addoption('--image', action="append", type="string",
                     help=Image.__doc__, default=[])

def pytest_configure(config):
    for name, value in vars(default_config).iteritems():
        if name == 'images':
            continue
        new_value = getattr(config.option, name)
        if new_value != None:
            if type(value) == list:
                new_value = new_value.split(',')
            setattr(default_config, name, new_value)
    images = []
    for image in config.option.image:
        args, kwargs = parse_option(image)
        images.append(Image(*args, **kwargs))
    # Prepend the command-line images to the defaults so the command-line images
    # take priority
    images.extend(default_config.images)
    default_config.images = images

    default_config.post_config()

def pytest_generate_tests(metafunc):
    if "image_finder" in metafunc.funcargnames:
        ImageFinder.parametrize(metafunc, 'image_finder',
                                get_test_distros(metafunc.function),
                                get_test_archs(metafunc.function))
