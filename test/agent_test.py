from . import harness

class TestAgent(harness.TestCase):

    ''' Agent tests. We test for installation and dkms variants.
    
    We do these on both main distros (Ubuntu and CentOS).  We also perform a
    more thorough test that exercises the introspection functionality of an
    installed agent. We launch clone/hoard/dropall cycles to get the maximum
    bang for buck from free page detection. We exercise this cycle on both
    distros and *all* bitnesses (32 bit, PAE, 64 bit).  Hence the
    parameterization at the bottom. '''

    @harness.distrotest()
    def test_agent_double_install(self, image_finder):
        with self.harness.booted(image_finder) as master:
            # Reinstall the agent. Shouldn't see any errors.
            # NOTE: The agent is installed automatically by
            # the harness by default. See the booted() function
            # for more information.
            master.install_agent()

    @harness.distrotest()
    def test_agent_install_remove_install(self, image_finder):
        with self.harness.booted(image_finder) as master:
            # Should be able to uninstall and install.
            master.remove_agent()
            master.install_agent()
