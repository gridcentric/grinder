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
