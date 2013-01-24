import os

from novaclient.v1_1.client import Client

class GcApi(object):
    '''Wrap the gridcentric API.
    This object wraps around the Gridcentric API,
    so that future API changes can be easily adapted to
    and versioned without changing all tests. This object
    was actually introduced for the Diablo -> Essex merge
    but although we longer support a Diablo API, it may
    still be useful in the future.'''
    
    def __init__(self, novaclient):
        self.novaclient = novaclient

    def discard_instance(self, *args, **kwargs):
        return self.novaclient.gridcentric.discard(*args, **kwargs)

    def launch_instance(self, *args, **kwargs):
        params = kwargs.get('params', {})
        guest = params.get('guest', {})
        target = params.get('target', "0")
        user_data = params.get('user_data', None)
        security_groups = params.get('security_groups', None)
        result = self.novaclient.gridcentric.launch(*args, target=target, user_data=user_data, guest_params=guest, security_groups=security_groups)
        return map(lambda x: x._info, result)

    def bless_instance(self, *args, **kwargs):
        return map(lambda x: x._info, self.novaclient.gridcentric.bless(*args, **kwargs))

    def list_blessed_instances(self, *args, **kwargs):
        return map(lambda x: x._info, self.novaclient.gridcentric.list_blessed(*args, **kwargs))

    def list_launched_instances(self, *args, **kwargs):
        return map(lambda x: x._info, self.novaclient.gridcentric.list_launched(*args, **kwargs))

    def migrate_instance(self, *args, **kwargs):
        return self.novaclient.gridcentric.migrate(*args, **kwargs)

    def install_agent(self, *args, **kwargs):
        return self.novaclient.gridcentric.install_agent(*args, **kwargs)

def create_nova_client(config):
    '''Creates a nova Client from the environment variables.'''
    from novaclient import shell
    extensions = shell.OpenStackComputeShell()._discover_extensions("1.1")
    if 'gridcentric' not in [e.name for e in extensions] and \
       'gridcentric_python_novaclient_ext' not in [e.name for e in extensions]:
        raise Exception("You don\'t have the gridcentric extension installed." \
                        "Try 'pip install gridcentric-novaclient-python-ext'.")
    return Client(extensions=extensions,
                  username=os.environ['OS_USERNAME'],
                  api_key=os.environ['OS_PASSWORD'],
                  project_id=os.environ['OS_TENANT_NAME'],
                  auth_url=os.environ['OS_AUTH_URL'],
                  region_name=os.environ.get('OS_REGION_NAME', None),
                  service_type=os.environ.get('NOVA_SERVICE_TYPE', 'compute'),
                  service_name=os.environ.get('NOVA_SERVICE_NAME', 'nova'))

def create_client(config):
    '''Creates a nova Client with a gcapi client embeded.'''
    client = create_nova_client(config)
    return (client, GcApi(client))
