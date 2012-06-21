import logging
import sys

# We can log to stdout because py.test captures and saves all of the output.
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
log = logging.getLogger('openstack-test')
log.propagate = False
log.setLevel(logging.DEBUG)
log.addHandler(handler)
