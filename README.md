To run, use the standalone `py.test` binary:

    ./py.test grinder

For verbose non-captured output:

    ./py.test --capture=no -vvv grinder

You can use typical pytest options:

    ./py.test -k only_this_test --collectonly grinder

For the brave & well (cluster) endowed:

    easy_install -U pytest-xdist && py.test -n 6 grinder

The above command will fork and run 6 test in parallel. Because of increased
load, latency increases and some test operations may timeout. YMMV.

Run `py.test --help grinder` to see the configuration options. Look at the
headings below for more information on options. You can change which hosts the
test runs on, for instance, with:
    
    ./py.test --hosts=node1,node2 grinder

To make using py.test less tedious, store your favourite command-line options in
pytest.ini. Here's an example:

    $ cat pytest.ini
    [pytest]
    addopts=-vvv --capture=no --leave_on_failure

Requirements
------------

Alternatively to using the included `py.test`, you can install `pytest` on your
own and use it:

    easy_install -U pytest

From wherever you choose to run Grinder, you should have the ptyhon-novaclient
package installed. Additionally, you need to have Gridcentric's nova client
extension, version 1.1.1244 or greater. An easy way to install it is:

    pip install --user gridcentric_python_novaclient_ext

For further information look into: http://docs.gridcentric.com/openstack/installation.html

You should have the appropriate environment variables set to be able to access
the OpenStack cluster being tested, with *admin* privileges:

    OS_TENANT_NAME=admin_tenant
    OS_USERNAME=joe_admin
    OS_PASSWORD=sup3r_s3cr3t
    OS_AUTH_URL=http://keystone_host:5000/v2.0

Or, you can pass them along as options:

    ./py.test grinder --os_tenant_name=admin_tenant \
    --os_username=joe_admin \
    --os_password=sup3r_s3cr3t \
    --os_auth_url=http://keystone_host:5000/v2.0

On guests, we require password-less ssh login to the root account, or to an
account with password-less sudo. For that you need to add your ssh keys to the
nova key-pair list, and let Grinder know which key-pair name to use:

    nova keypair-add --pub_key ~/.ssh/id_rsa.pub `whoami`
    ./py.test --guest_key_name=`whoami` grinder

If running the test from outside the OpenStack cluster, you will also need to
configure the rules for the default security group to allow icmp and ssh
traffic to VMs:

    nova secgroup-add-rule default tcp 22 22 0.0.0.0/0
    nova secgroup-add-rule default icmp -1 -1 0.0.0.0/0

Or, you can create your own security group for the test instances, with ssh and
icmp open, and pass it along:

    nova secgroup-create grinder 'Sec group for testing'
    nova secgroup-add-rule grinder tcp 22 22 0.0.0.0/0
    nova secgroup-add-rule grinder icmp -1 -1 0.0.0.0/0
    ./py.test --security_group=grinder grinder

To run some tests, you will need a key installed on the physical hosts as well.
Grinder requires password-less login to the root account, or to an account
capable of password-less sudo.  The user is controlled by the `--host_user`
option, and the path to the private key (if not `~/.ssh/id_rsa`) is set with
the `--host_key_path` option.

It's a good idea to set the environment variable `OS_NO_CACHE=1` to prevent
novaclient form interrupting tests by asking about keyrings.

Finally, the Grinder testing suite requires Folsom or later environments to
test all features. Some tests will be skipped in Essex.

Configuring Images
-----------------

Grinder will run all tests on each image in a list of images you provide. This
is to ensure all functionality works on the typical guest images you use in
your cloud. A typical image configuration stanza looks like this:

    --image=precise-server.img,distro=ubuntu,arch=64,user=ubuntu

You can add this to your `pytest.ini` or your command line. You can add as many
of this as images you want to test. Specifically, the stanza above means that
the glance image `precise-server.img` will be used, and that the image is an
Ubuntu distribution with a 64 bit kernel. The user `ubuntu` has password-less
sudo rights, and allows password-less ssh login using the key set with the
`--guest_key_name` option. Note that this is default behavior for Ubuntu
cloud images with nova key injection. For CentOS images, you would typically
set the user to `root`.

Look into the `Image` class in `grinder/config.py` for more options.

Tempest-based configuration
---------------------------

Grinder can read most of its configuration parameters from Tempest, the
OpenStack integration test suite.

    https://github.com/openstack/tempest

This is specified through the option `tempest_config`:

    --tempest_config=/path/to/tempest.conf

Grinder will use the following keys in tempest.conf:

* `username`, from the section `[compute-admin]`
* `password`, `[compute-admin]`
* `tenant_name`, `[compute-admin]`
* `admin_username`, section `[identity]`, as fallback if the `[compute_admin]` section is incomplete or lacking
* `admin_password`, `[identity]`, fallback
* `admin_tenant_name`, `[identity]`, fallback
* `uri`, `[identity]`
* `region_name`, `[identity]`, if present
* `image_ref`, `[compute]`
* `flavor_ref`, `[compute]`
* `ssh_user`, `[compute]`

The `uri`, `region_name`, `username`, `password`, and `tenant_name` keys (or
their fallbacks) are used for authenticating to the OpenStack cluster.

The `image_ref`, `flavor_ref` and `ssh_user` keys are used to configure the
image for running tests. Grinder will further require setting the following two
options related to this image:

* `tc_distro` - the distro name
* `tc_arch` - the arch

Here is an example of a command line that uses tempest.conf:

    py.test --tempest_config=/path/to/tempest.conf --tc_distro=ubuntu --tc_arch=64 grinder

List of hosts
-------------

The list of hosts used for testing is generated as follows:
* If the option `hosts` is present in either `pytest.ini` or the command line,
  its value is used for the list.
* Otherwise, the value of `hosts` is the list of all hosts that nova API is
  aware of.
* In either case, only those hosts in the list that are running the service
  `gridcentric` are retained.
* *Folsom and later only*: All resulting hosts should belong to the 
  availability zone set through the `default_az` configuration option (defaults
  to 'nova').

The list `hosts_without_gridcentric` is used for migration tests. It is
generated as follows:
* If it is provided as an option in `pytest.ini` or on the command line, the
  value of that option is used as the list of hosts.
* Otherwise, the list of all hosts obtained via nova API (and not running
  `gridcentric`) is used.
* If the list is empty and local host is not running `gridcentric`, then the local
  host is used.

**NOTE:** For Grinder to be able to get the list of all hosts from nova
API, a reasonably recent version of python-novaclient has to be installed, and
Grinder must be using admin privileges in order to query all hosts in the
cluster. Otherwise, Grinder only uses `hosts` and `hosts_without_gridcentric`
as specified in the configuration.

Further options
--------------

Please have a look into `grinder/config.py`. All configuration options are
documented as attributes of the Config and Image classes. Any such attribute
can be set through the command line or `pytest.ini`. For example,
`--skip_migration_tests`.

Licensing
--------

Grinder is released under the terms of the Apache license. This suite
redistributes `py.test`, taken from the pytest project, and distributed under
the terms of the MIT license.
