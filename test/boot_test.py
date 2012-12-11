from novaclient.exceptions import ClientException

from . import harness

class TestBoot(harness.TestCase):

    @harness.distrotest()
    def test_boot(self, image_finder):
        with self.harness.booted(image_finder) as master:
            assert True
