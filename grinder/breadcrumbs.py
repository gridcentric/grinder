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
        self.filename = '/dev/shm/test-breadcrumbs-%d' % random.randint(0, 1<<32)

    class Snapshot(object):
        def __init__(self, breadcrumbs):
            self.trail = list(breadcrumbs.trail)
            self.filename = breadcrumbs.filename

        def instantiate(self, server):
            result = Breadcrumbs(server)
            result.trail = list(self.trail)
            result.filename = self.filename
            return result

    def snapshot(self):
        return Breadcrumbs.Snapshot(self)

    def add(self, breadcrumb):
        self.assert_trail()
        breadcrumb = '%d: %s' % (len(self.trail), breadcrumb)
        log.debug('Adding breadcrumb "%s"', breadcrumb)
        self.instance.root_command('echo %s >> %s' % (breadcrumb, self.filename))
        self.trail.append(breadcrumb)
        self.assert_trail()

    def assert_trail(self):
        shell = self.instance.get_shell()
        if len(self.trail) == 0:
            self.instance.root_command('test ! -e %s' % self.filename)
        else:
            stdout, stderr = self.instance.root_command('cat %s' % self.filename)
            log.debug('Got breadcrumbs: %s', stdout.split('\n'))
            assert [x.strip('\r') for x in stdout.split('\n')] == list(self.trail)
