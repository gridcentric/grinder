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

import types
import time
import os
import urlparse
import urllib

from . logger import log
from . config import default_config

import novaclient.exceptions
import cinderclient.exceptions

def assert_raises(exception_type, command, *args, **kwargs):
    try:
        command(*args, **kwargs)
        assert False and 'Expected exception of type %s' % exception_type
    except Exception, e:
        if not isinstance(e, exception_type):
            log.exception('Expected exception of type %s, got %s instead.' %
                          (exception_type, type(e)))
            raise
        log.debug('Got expected exception %s', e)
        return e

class Notifier(object):

    '''Adds pre_X(o) and post_X(o, r) to methods decorated with notify.'''
    def __init__(self):
        self.__pre = {}
        self.__post = {}

    def __getattr__(self, name):
        if name.startswith('pre_'):
            event = self.__pre
        elif name.startswith('post_'):
            event = self.__post
        else:
            raise AttributeError(name)

        method_name = name.split('_', 1)[1]
        try:
            method = getattr(self, method_name)
        except AttributeError:
            raise AttributeError(name)

        if type(method) != types.MethodType:
            raise AttributeError(name)
        def watch(callback):
            self.__watch(event, method_name, callback)
        return watch
        
    def __watch(self, event, method_name, callback):
        callbacks = event.get(method_name, [])
        callbacks.append(callback)
        event[method_name] = callbacks

    def __fire(self, event, method_name, *args):
        callbacks = event.get(method_name, [])
        for callback in callbacks:
            callback(*args)

    @staticmethod
    def notify(fn):
        def wrapped(*args, **kwargs):
            self = args[0]
            self.__fire(self.__pre, fn.__name__, self)
            r = fn(*args, **kwargs)
            self.__fire(self.__post, fn.__name__, self, r)
            return r
        return wrapped

def list_filter(l, exclude=None, include=None, only=None):
    if exclude == None:
        exclude = []
    if include != None:
        l = l + include
    if only == None:
        only = l
    return [e for e in l if e not in exclude and e in only]

def wait_for(message, condition, interval=1):
    duration = int(default_config.ops_timeout)
    log.info('Waiting %ss for %s', duration, message)
    start = time.time()
    while True:
        if condition():
            return
        remaining = start + duration - time.time()
        if remaining <= 0:
            raise Exception('Timeout: waited %ss for %s' % (duration, message))
        time.sleep(min(interval, remaining))

def wait_for_ping(addrs):
    assert len(addrs) > 0
    ip = addrs[0]
    wait_for('ping %s to respond' % ip,
             lambda: os.system('ping -n %s -c 1 -W 1 > /dev/null 2>&1' % ip) == 0)

# The .get() method and id field apply to nova servers and cinder volumes. More
# generally to all subclasses of an Openstack Resource.
def wait_while_status(os_resource, status):
    def condition():
        if os_resource.status.lower() != status.lower():
            return True
        os_resource.get()
        return False
    wait_for('%s on %s ID %s to finish' % \
             (status, os_resource.__class__.__name__, \
              str(os_resource.id)), condition)

def wait_for_status(os_resource, status):
    def condition():
        if os_resource.status.lower() == status.lower():
            return True
        os_resource.get()
        return False
    wait_for('%s ID %s to reach status %s' % (os_resource.__class__.__name__, \
              str(os_resource.id), status), condition)

def wait_while_exists(os_resource):
    def condition():
        try:
            os_resource.get()
            return False
        # I hate this. But each client redefines the exception. And there is
        # apparently no way to work back from the os_resource to the client
        # that produced it and the exceptions it will raise
        except (novaclient.exceptions.NotFound, cinderclient.exceptions.NotFound):
            return True
    wait_for('%s %s to not exist' % \
             (os_resource.__class__.__name__, str(os_resource.id)), condition)

def fix_url_for_yum(url):
    # Yum's URL parser cannot deal with commas and such.
    s = urlparse.urlsplit(url)
    parts = [s[0], s[1]]
    for i in range(2, len(s)):
        elem = urllib.quote(s[i])
        parts.append(elem)
    return urlparse.urlunsplit(parts)
