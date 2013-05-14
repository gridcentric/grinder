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

from novaclient.v1_1.client import Client

class GcApi(object):
    '''Wrap the gridcentric API.
    This object wraps around the Gridcentric API,
    so that future API changes can be easily adapted to
    and versioned without changing all tests. This object
    was actually introduced for the Diablo -> Essex merge
    but although we no longer support a Diablo API, it may
    still be useful in the future.'''
    
    def __init__(self, novaclient):
        self.novaclient = novaclient

    def discard_instance(self, *args, **kwargs):
        return self.novaclient.gridcentric.discard(*args, **kwargs)

    def launch_instance(self, *args, **kwargs):
        params = kwargs.get('params', {})
        guest = params.get('guest', {})
        target = params.get('target', "0")
        launch_kwargs = {}
        for param in ('name', 'user_data', 'security_groups',
                      'availability_zone', 'num_instances', 'key_name'):
            if param in params:
                launch_kwargs[param] = params[param]
        result = self.novaclient.gridcentric.launch(*args, target=target,
                guest_params=guest, **launch_kwargs)
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
    if not set(['gridcentric', 'cobalt', 'gridcentric_python_novaclient_ext',
        'cobalt_python_novaclient_ext']) & set([e.name for e in extensions]):
        raise Exception("You don\'t have the gridcentric extension installed." \
                        "Try 'pip install gridcentric-python-novaclient-ext'.")
    return Client(extensions=extensions,
                  username=config.os_username,
                  api_key=config.os_password,
                  project_id=config.os_tenant_name,
                  auth_url=config.os_auth_url,
                  region_name=config.os_region_name,
                  no_cache=os.environ.get('OS_NO_CACHE', 0) and True,
                  http_log_debug=config.http_log_debug,
                  service_type=os.environ.get('NOVA_SERVICE_TYPE', 'compute'),
                  service_name=os.environ.get('NOVA_SERVICE_NAME', 'nova'))

def create_client(config):
    '''Creates a nova Client with a gcapi client embeded.'''
    client = create_nova_client(config)
    return (client, GcApi(client))
