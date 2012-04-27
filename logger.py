import logging
import sys

log = logging.getLogger('openstack-test')
log.setLevel(logging.DEBUG)
# We can log to stdout because py.test captures and saves all of the output.
log.addHandler(logging.StreamHandler(sys.stdout))
