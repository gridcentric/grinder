# Copyright 2011 GridCentric Inc.
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

import pytest
from . conftest import parse_image_options
from . util import assert_raises

def assert_image(input, name, distro, arch, **kwargs):
    img = parse_image_options(input)
    assert img.name == name
    assert img.distro == distro
    assert img.arch == arch
    for key,val in kwargs.items():
        assert getattr(img, key) == val

def test_image_parsing():
    assert_image("ubuntu64,distro=ubuntu,arch=64", 'ubuntu64', 'ubuntu', '64')
    assert_image("ubuntu64,ubuntu,64", 'ubuntu64', 'ubuntu', '64')
    assert_image("ubuntu64,distro=ubuntu,arch=64,cloudinit",
                 'ubuntu64', 'ubuntu', '64', cloudinit = True)
    assert_image("ubuntu64,distro=ubuntu,arch=64,-cloudinit",
                 'ubuntu64', 'ubuntu', '64', cloudinit = False)
    assert_image("ubuntu64,distro=ubuntu,arch=64,key_name=test",
                 'ubuntu64', 'ubuntu', '64', key_name = 'test')
    assert_image("ubuntu64,distro=ubuntu,arch=64,user=test",
                 'ubuntu64', 'ubuntu', '64', user = 'test')
    assert_image("ubuntu64,distro=ubuntu,arch=64,key_path=test",
                 'ubuntu64', 'ubuntu', '64', key_path = 'test')
    assert_image("ubuntu64,distro=ubuntu,arch=64,flavor=test",
                 'ubuntu64', 'ubuntu', '64', flavor = 'test')
    assert_image("ubuntu64,distro=ubuntu,arch=64,flavor=m1.tiny,"
                 "user=ubuntu,key_path=/home/grinder/.ssh/id_rsa,"
                 "key_name=grinder,cloudinit",
                 'ubuntu64', 'ubuntu', '64', flavor = 'm1.tiny',
                 user = 'ubuntu', key_path = '/home/grinder/.ssh/id_rsa',
                 key_name = 'grinder', cloudinit = True)
    assert_raises(Exception, parse_image_options,
                  "ubuntu64,distro=ubuntu,arch=64,-name")
    assert_raises(Exception, parse_image_options,
                  "ubuntu64,distro=ubuntu,arch=64,-distro")
    assert_raises(Exception, parse_image_options,
                  "ubuntu64,distro=ubuntu,arch=64,foo=bar")
    assert_raises(Exception, parse_image_options,
                  "ubuntu64,distro=ubuntu,arch=64,name")
    assert_raises(Exception, parse_image_options,
                  "ubuntu64,distro=ubuntu,arch=64,distro")
    assert_raises(Exception, parse_image_options,
                  "ubuntu64,ubuntu,64,distro")
