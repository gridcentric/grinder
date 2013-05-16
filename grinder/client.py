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

class GcApi(object):
    '''Wrap the gridcentric API.
    This object wraps around the Gridcentric API,
    so that future API changes can be easily adapted to
    and versioned without changing all tests. This object
    was actually introduced for the Diablo -> Essex merge.
    It is now used to bridge the Folsom -> Grizzly transition
    during which we renamed the extension to cobalt. Note
    the client is expected to support the old 'gridcentric'
    and the new 'cobalt' extension names-spaces.'''
    
    def __init__(self, novaclient):
        self.novaclient = novaclient

    def __gridcentric_method(self, method):
        return getattr(self.novaclient.gridcentric, method)

    def __cobalt_method(self, method):
        return getattr(self.novaclient.cobalt, method)

    def __cobalt_select_method(self, method):
        compat_dict = {
            'discard'       : 'delete_live_image',
            'list_launched' : 'list_live_image_servers',
            'list_blessed'  : 'list_live_images',
            'bless'         : 'create_live_image',
            'launch'        : 'start_live_image' }
        if method not in compat_dict.keys():
            return self.__gridcentric_method(method)
        if not hasattr(self.novaclient, 'cobalt'):
            return self.__gridcentric_method(method)
        cobalt_method = compat_dict[method]
        if hasattr(self.novaclient.cobalt, compat_dict[method]):
            return self.__cobalt_method(compat_dict[method])
        return self.__gridcentric_method(method)

    def discard_instance(self, *args, **kwargs):
        return self.__cobalt_select_method('discard')(*args, **kwargs)

    def launch_instance(self, *args, **kwargs):
        params = kwargs.get('params', {})
        guest = params.get('guest', {})
        target = params.get('target', "0")
        launch_kwargs = {}
        for param in ('name', 'user_data', 'security_groups',
                      'availability_zone', 'num_instances', 'key_name',
                      'scheduler_hints'):
            if param in params:
                launch_kwargs[param] = params[param]
        result = self.__cobalt_select_method('launch')(*args, target=target,
                guest_params=guest, **launch_kwargs)
        return map(lambda x: x._info, result)

    def bless_instance(self, *args, **kwargs):
        return map(lambda x: x._info,
                    self.__cobalt_select_method('bless')(*args, **kwargs))

    def list_blessed_instances(self, *args, **kwargs):
        return map(lambda x: x._info,
                    self.__cobalt_select_method('list_blessed')(*args, **kwargs))

    def list_launched_instances(self, *args, **kwargs):
        return map(lambda x: x._info,
                    self.__cobalt_select_method('list_launched')(*args, **kwargs))

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
    from novaclient.v1_1.client import Client
    return Client(
        extensions=extensions,
        username=config.os_username,
        api_key=config.os_password,
        project_id=config.os_tenant_name,
        auth_url=config.os_auth_url,
        region_name=config.os_region_name,
        no_cache=os.environ.get('OS_NO_CACHE', 0) and True,
        http_log_debug=config.http_log_debug)

def create_cinder_client(config):
    from cinderclient.client import Client
    return Client(1,
        username=config.os_username,
        api_key=config.os_password,
        project_id=config.os_tenant_name,
        auth_url=config.os_auth_url,
        region_name=config.os_region_name)

def create_client(config):
    '''Creates a nova Client with a gcapi client embeded.'''
    nova = create_nova_client(config)
    cinder = create_cinder_client(config)
    return (nova, GcApi(nova), cinder)
