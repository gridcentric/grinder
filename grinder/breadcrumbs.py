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

import random

from . logger import log

class Breadcrumbs(object):

    def __init__(self, instance):
        self.instance = instance
        self.trail = []
        self.data = None

    class Snapshot(object):
        def __init__(self, breadcrumbs):
            self.trail = list(breadcrumbs.trail)
            self.data = breadcrumbs.data

        def instantiate(self, server):
            result = Breadcrumbs(server)
            result.trail = list(self.trail)
            result.data = self.data
            return result

    def snapshot(self):
        return Breadcrumbs.Snapshot(self)

    def add(self, breadcrumb):
        self.assert_trail()
        breadcrumb = '%d: %s' % (len(self.trail), breadcrumb)
        log.debug('Adding breadcrumb "%s"', breadcrumb)
        self._put(breadcrumb)
        self.trail.append(breadcrumb)
        self.assert_trail()

    def assert_trail(self):
        if len(self.trail) == 0:
            assert self._emptyp()
        else:
            # Strip trailing newline, we don't want an empty line at the end of
            # the list.
            contents = self._get().strip()
            log.debug('Got breadcrumbs: %s', contents.split('\n'))
            assert [x.strip('\r') for x in contents.split('\n')] == list(self.trail)

    def _put(self, buf):
        raise NotImplementedError()

    def _get(self):
        raise NotImplementedError()

    def _emptyp(self):
        raise NotImplementedError()

class SSHBreadcrumbs(Breadcrumbs):

    def __init__(self, instance):
        Breadcrumbs.__init__(self, instance)
        self.data = '/dev/shm/test-breadcrumbs-%d' % random.randint(0, 1<<32)

    def _put(self, buf):
        self.instance.root_command('echo %s >> %s' % (buf, self.data))

    def _get(self):
        stdout, stderr = self.instance.root_command('cat %s' % self.data)
        return stdout

    def _emptyp(self):
        try:
            self.instance.root_command('test ! -e %s' % self.data)
            return True
        except:
            return False

class LinkBreadcrumbs(Breadcrumbs):
    """
    Windows Link-based breadcrumb. Communicates with the
    TestListener service on a Windows guest.
    """

    def __init__(self, instance):
        Breadcrumbs.__init__(self, instance)

    def _put(self, buf):
        self.instance.get_shell().check_output('breadcrumb-add %s' % buf)

    def _get(self):
        buf, _ = self.instance.get_shell().check_output('breadcrumb-list',
                                                        expected_output=None)
        return buf.replace('\r', '').strip()

    def _emptyp(self):
        return (len(self._get()) == 0)
