To run, use the standalone `py.test` binary, `pytest.py`:

    ./pytest.py

Alternatively, you can install `py.test` and use it:

To install py.test:

    easy_install -U pytest

Install your your ssh keys for booting VMs:

    nova keypair-add --pub_key ~/.ssh/id_rsa.pub `whoami`

If running the test from outside the openstack cluster, the default
group needs to be configured to allow icmp and ssh traffic to VMs:

    nova secgroup-add-rule default tcp 22 22 0.0.0.0/0
    nova secgroup-add-rule default icmp -1 -1 0.0.0.0/0

Run with py.test:

    py.test --guest_key_name=`whoami` --capture=no -vvv

For the brave & well (cluster) endowed:

    easy_install -U pytest-xdist && py.test -n 6

The above command will fork and run 6 test in parallel. Because of increased
load, latency increases and some test operations will timeout. YMMV.

Run `py.test --help` to see the configuration options. You can change which hosts
the test runs on, for instance, with
    
    py.test --hosts=node1,node2

To make using py.test less tedious, store your favourite command-line options in
pytest.ini. Here's mine:

    $ cat pytest.ini
    [pytest]
    addopts=--hosts=node1,node2 -vvv --capture=no

A note on ssh keys
------------------

To run some tests, you will need a key installed on the physical hosts as well.
The user is controlled by the `--host_user` option, and the key is set by the
`--host_key_path` option.

This user should either be root, or have passwordless sudo access.

tempest configuration
---------------------

The test suite can read some configuration parameters from tempest, the OpenStack integration test suite.
The way to specify that, we provide option `tempest_config`, like so:

    --tempest_config=/path/to/tempest.conf

If this option exists, the following options must exist too:

* `tc_distro` - the distro name
* `tc_arch` - the arch
* `tc_user` - the username used for login to the instance

Test suite will read image ID or name from section `[compute]`, key `image_ref` in the `tempest.conf` file
and flavor ID from section `[compute]`, key `flavor_ref`.

Here is an example of a command line runnig the test suite that uses tempest.conf:

    py.test --tempest_config=/path/to/tempest.conf --tc_distro=ubuntu --tc_arch=64 --tc_user=root

List of hosts
-------------

The list of hosts used for testing is generated as follows:
* If option `hosts` is present in either `pytest.ini` or command line, its value is used
  for the list.
* Otherwise, the value of `hosts` is the list of all hosts that nova API is aware of.
* From the list, only those hosts are retained that are running the service `gridcentric`.

List `hosts_without_openstack` is used for migration test. It is generated as follows:
* If it is provided as an option in `pytest.ini` or on the command line, the value of that
  option is used as the list of hosts.
* Otherwise, the list of all hosts obtained via nova API (and not running
  `gridcentric`) is used.
* If the list is empty and local host is not running `gridcentric`, then the local
  host is used.

**NOTE:** For the test suite to be able to get the list of all hosts from nova API, a reasonably
recent version of python-novaclient has to be installed. Otherwise, the test suite only uses
`hosts` and `hosts_without_openstack` as specified in the configuration.

If option `skip_migration_tests` is specified, migration tests are skipped.
