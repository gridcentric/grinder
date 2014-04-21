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

import copy
import inspect
import os
import sys
import time
import types
import urllib
import urlparse
import traceback

from . logger import log
from . config import default_config

from threading import Thread, Condition

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

class NestedExceptionWrapper(object):
    def __init__(self):
        pass

    def __enter__(self):
        self.type_, self.value, self.tb = sys.exc_info()

    def __exit__(self, exception_type, exception_value, tb):
        # If there is an exception while this object is alive we want to log the
        # original exception as it is why the test failed.
        if exception_type is not None:
            log.error("An exception occurred cleaning up from this test." +
                          "The real reason the test failed was: ")
            log.error(' '.join(traceback.format_exception(self.type_, self.value, self.tb)))
            return False

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

def wait_for(message, condition, interval=1, duration=None):
    if duration is None:
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

def mb2pages(mb):
    return mb * 256

class Background(object):
    """
    A decorator for turning a function into an object which runs a periodic,
    background task in a separate thread. The background thread is started when
    the returned object's __enter__ function is called and cleaned up when the
    __exit__ function is called.

    If the decorator's target function ever raises an exception, the background
    thread stops and the exception is re-raised in the main thread during
    __exit__.

    If a verifier function is provided, the target function must have an
    argument called context and this argument must have a default value. This
    argument must not be provided at the call site. This function will be
    automatically provided by the background thread and is a way to share data
    between multiple invocations of the target function. On the first call, a
    deep copy of the default value for context will be passed to the target
    function. The deep copy prevents invocations from unintentionally modifying
    the object specified in the function definition. On subsequent calls, the
    return value from the previous call to the target function is passed in as
    the context.

    To use the context an a reference to a mutable object, return the reference
    after making any modifications to it in the body of the target function. To
    use the context as an accumulator, return the updated value.

    An optional verifier function can be passed to the decorator. If provided,
    this function will be called during clean up (i.e. from the main thread's
    context during __exit__) with the last context. If the target function was
    never called, the verifier will be passed a deep copy of the default value
    for the context. Otherwise, the value returned by the last call to the
    target function will be provided to the verifier.
    """
    def __init__(self, verifier=None, interval=1.0):
        self.interval = interval
        self.verifier = verifier

    def __call__(self, func):
        def wrapped(*args, **kwargs):
            return Background.Executor(self.interval, self.verifier,
                                       func, args, kwargs)
        return wrapped

    class Executor(Thread):
        def __init__(self, interval, verifier, func, args, kwargs):
            super(Background.Executor, self).__init__()
            self.cond = Condition()
            self.stop = False
            self.interval = interval
            self.verifier = verifier
            self.func = func
            self.args = args
            self.kwargs = kwargs

            # Do some introspection to ensure a default value for context was
            # provided in the function definition if we're using a verifier. We
            # strictly enforce that a default value is provided to avoid
            # surprises (especially because otherwise the verify function will
            # be called with seemingly 'random' return values from the function.
            argspec = inspect.getargspec(self.func)
            try:
                defaults_dict = dict(zip(reversed(argspec.args),
                                         reversed(argspec.defaults)))
            except TypeError:
                # No args or default values.
                defaults_dict = {}

            if callable(self.verifier) and not defaults_dict.has_key("context"):
                raise TypeError("Backgrounded function '%s' " % self.func.__name__ +
                               "must have an argument called 'context' with " +
                               "a default value for it.")

            # Should we do the context passing magic? We only do this if a
            # context kwarg is specified for the background task function. Note
            # that we also enforce that a context arg is provided if using a
            # verifier function.
            self.use_context = defaults_dict.has_key("context")

            # If we're using the context magic, make sure the caller isn't
            # providing a value for 'context' as either a positional argument
            # or a keyword argument at the call site. We magically patch in
            # this value and don't want to silently replace the user-provided
            # value to avoid surprises.
            caller_pos_args = dict(zip(argspec.args, self.args))
            if self.use_context and caller_pos_args.has_key("context"):
                raise TypeError("Backgrounded function '%s' " % self.func.__name__ +
                                "called with 'context' provided as a " +
                                "positional argument (value=%s)." % \
                                    str(caller_pos_args["context"]))

            if self.use_context and self.kwargs.has_key("context"):
                raise TypeError("Backgrounded function '%s' " % self.func.__name__ +
                                "called with 'context' provided as a " +
                                "keyword argument (value=%s)." % \
                                    str(self.kwargs["context"]))

            # Prime the default value as the first value we pass in via the
            # 'context' kwargs. Take care to NOT use the default value we
            # extracted out of the context directly because we DO NOT want to
            # modify the global object attached to the function definition.
            if self.use_context:
                self.kwargs["context"] = copy.deepcopy(defaults_dict["context"])

            self.exception = None

        def run(self):
            self.cond.acquire()
            try:
                while not self.stop:
                    try:
                        # Run target function and update the context. The
                        # context automatically gets passed since we stuff it
                        # into self.kwargs after each call.
                        result = self.func(*self.args, **self.kwargs)
                        if self.use_context:
                            self.kwargs["context"] = result
                    except Exception, ex:
                        self.exception = sys.exc_info()
                        return
                    self.cond.wait(self.interval)
            finally:
                self.cond.release()

        def join(self, timeout=None):
            self.cond.acquire()
            self.stop = True
            self.cond.notifyAll()
            self.cond.release()
            super(Background.Executor, self).join(timeout)

            if self.exception is not None:
                raise self.exception[0], self.exception[1], self.exception[2]

            if callable(self.verifier):
                self.verifier(self.kwargs["context"])

        def __enter__(self):
            log.info("Entering background thread with func: %s", self.func.__name__)
            self.start()

        def __exit__(self, typ, value, traceback):
            self.join()
            log.info("Exiting background thread with func: %s", self.func.__name__)

def install_policy(gcapi, policy, timeout=60):
    # On a busy system this may timeout after the default RPC timeout, which
    # is typically less than the grinder operations timeout (1 min vs 10
    # min).
    start = time.time()
    while True:
        try:
            gcapi.install_policy(policy, wait=True)
            return
        except novaclient.exceptions.BadRequest:
            elapsed = time.time() - start
            if elapsed > timeout:
                raise Exception("Failed to install policy after " +
                                "%0.2f of %0.2f seconds." % \
                                    (float(elapsed), float(timeout)))
            else:
                log.debug("Policy install failed after " +
                          "%0.2f of %0.2f seconds. Retrying." % \
                              (float(elapsed), float(timeout)))

# Backport datetime.total_seconds() from Python 2.7 since grinder
# needs to work on Python 2.6 (on RDO).
def timedelta_total_seconds(delta):
    total_seconds = 0.0
    total_seconds += delta.days * 86400 # 24 * 60 * 60
    total_seconds += delta.seconds
    total_seconds += delta.microseconds / 1000000
    return total_seconds
