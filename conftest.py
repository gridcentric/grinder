from config import default_config

def pytest_funcarg__config(request):
    return 112

def pytest_addoption(parser):
    # Add options for each of the default_config fields.
    for name, value in vars(default_config).iteritems():
        if type(value) == list:
            help='default is %s (comma-separated list)' % ','.join(value)
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
