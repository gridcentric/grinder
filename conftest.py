from config import default_config
import os

def pytest_runtest_setup(item):
    # Can't import harness earlier because pytest screws up importing logger.
    import harness
    harness.test_name = item.reportinfo()[2]

def pytest_addoption(parser):
    # Add options for each of the default_config fields.
    for name, value in vars(default_config).iteritems():
        if type(value) == list:
            help='default is %s (comma-separated list)' % ','.join(str(value))
        else:
            help='default is %s' % value
        parser.addoption('--%s' % name, action="store", type="string",
                         default=None, help=help)

def pytest_configure(config):
    for name, value in vars(default_config).iteritems():
        new_value = getattr(config.option, name)
        if new_value != None:
            if type(value) == list:
                new_value = new_value.split(',')
            setattr(default_config, name, new_value)
