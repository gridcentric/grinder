from novaclient.exceptions import ClientException
import py.test 

from . import harness
from . logger import log
from . util import assert_raises
from . host import Host

class TestMigration(harness.TestCase):

    def test_migration_errors(self, image_finder):
        if self.harness.config.skip_migration_tests:
            py.test.skip('Skipping migration tests')
        if len(self.harness.config.hosts_without_openstack) == 0:
            py.test.skip('Need at least one host without gridcentric to test for migration errors.')
        with self.harness.booted(image_finder) as master:
            host = master.get_host()
    
            def fail_migrate(dest):
                log.info('Expecting Migration %s to %s to fail', str(master.id), dest)
                master.breadcrumbs.add('pre expected fail migration to %s' % dest.id)
                e = assert_raises(ClientException,
                                  master.migrate,
                                  host, dest)
                assert e.code / 100 == 4 or e.code / 100 == 5
                master.assert_alive(host)
                master.breadcrumbs.add('post expected fail migration to %s' % dest.id)
    
            # Destination does not exist.
            fail_migrate(Host('this-host-does-not-exist', self.harness.config))
    
            # Destination does not have openstack.
            dest = Host(self.config.hosts_without_openstack[0], self.harness.config)
            fail_migrate(dest)
    
            # Cannot migrate to self.
            fail_migrate(host)

    def test_back_and_forth(self, image_finder):
        if self.harness.config.skip_migration_tests:
            py.test.skip('Skipping migration tests')
        if len(self.harness.config.hosts) < 2:
            py.test.skip('Need at least 2 hosts to do migration.')
        with self.harness.booted(image_finder) as master:
            host = master.get_host()
            dest = Host([h for h in self.config.hosts if h != host.id][0], self.harness.config)
            assert host.id != dest.id
            master.migrate(host, dest)
            master.migrate(dest, host)
            master.migrate(host, dest)
            master.migrate(dest, host)
