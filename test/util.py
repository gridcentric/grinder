import types
import time
import os
import urlparse
import urllib

from . logger import log
from . config import default_config

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

def list_filter(l, exclude=None, include=None):
    if exclude == None:
        exclude = []
    if include != None:
        l = l + include
    return [e for e in l if e not in exclude]

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
             lambda: os.system('ping %s -c 1 -W 1 > /dev/null 2>&1' % ip) == 0)

def fix_url_for_yum(url):
    s = urlparse.urlsplit(url)
    parts = [s[0], s[1]]
    for i in range(2, len(s)):
        elem = urllib.quote(s[i])
        parts.append(elem)
    return urlparse.urlunsplit(parts)
