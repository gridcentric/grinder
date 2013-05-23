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

import os
import pytest
import sys
import time

from threading import Lock, Condition

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

def test_list_filter():
    assert [3] == util.list_filter([1,2,3], exclude = [1,2])
    assert [1, 2, 3, 4, 5] == util.list_filter([1,2,3], include = [4, 5])
    assert [1] == util.list_filter([1,2,3], only=[1])
    assert [1, 4] == util.list_filter([1,2,3], exclude = [2, 3], include = [4])
    assert [1, 4] == util.list_filter([1,2,3,4], exclude = [2, 3], only = [1, 2, 4])
    assert [1, 4] == util.list_filter([1,2,3], include = [4], only = [1, 4])
    assert [1, 4] == util.list_filter([1,2,3,4], exclude = [2, 3], include = [5], only = [1, 2, 4])

def test_background():

    def watch_len_result_check(rvals):
        # From the background task interval and the runtime in the
        # main thread, we can estimate the number of times the
        # background thread will run.
        assert len(rvals) < 12
        assert len(rvals) > 8

    @util.Background(verifier=watch_len_result_check, interval=0.1)
    def watch_len(lock, lst, thresh, context=[]):
        with lock:
            try:
                assert len(lst) <= thresh
            except:
                raise
            context.append(len(lst))
            return context

    l = Lock()
    iput = []

    # We expect this to fail because the list length will exceed the
    # threshold in the background task.
    try:
        with watch_len(l, iput, 10):
            for i in xrange(0, 20):
                with l:
                    iput.append(True)
                time.sleep(0.1)
        assert False
    except:
        pass

    iput = []

    # This time it should succeed.
    with watch_len(l, iput, 15):
        for i in xrange(0, 10):
            with l:
                iput.append(True)
            time.sleep(0.1)

    iput = []

    # Nesting multiple instances of the same background task should work fine.
    with watch_len(l, iput, 15):
        with watch_len(l, iput, 15):
            for i in xrange(0, 10):
                with l:
                    iput.append(True)
                time.sleep(0.1)
