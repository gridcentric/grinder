import gridcentric_python_novaclient_ext

class NovaClientCapability(object):

    def __init__(self, capability):
        self.capability = capability

    def check(self, harness):
        return hasattr(gridcentric_python_novaclient_ext, 'CAPABILITIES') and \
            self.capability in gridcentric_python_novaclient_ext.CAPABILITIES

LAUNCH_NAME = NovaClientCapability('launch-name')

USER_DATA = NovaClientCapability('user-data')

SECURITY_GROUPS = NovaClientCapability('security-groups')
