# Copyright 2013 GridCentric Inc.
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

import util

class NotifierTester(util.Notifier):
    value = None

    @util.Notifier.notify
    def method(self, x):
        self.value = x
        return x

    def no_notify(self):
        pass

def test_notifier():
    tester = NotifierTester()
    def pre(o):
        assert o == tester
        assert tester.value == None
    def post(o, r):
        assert o == tester
        assert r == 5
        assert tester.value == 5
    tester.pre_method(pre)
    tester.post_method(post)
    assert 5 == tester.method(5)
    assert tester.value == 5

    # Not a method.
    e = pytest.raises(AttributeError, getattr, tester, 'pre_value')
    assert str(e.value) == 'pre_value'
    # No such attribute.
    e = pytest.raises(AttributeError, getattr, tester, 'pre_bad_method')
    assert str(e.value) == 'pre_bad_method'
    # There's no easy way to see if a method has a decorator, so we allow this.
    tester.pre_no_notify
