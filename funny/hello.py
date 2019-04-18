#-*- coding:utf-8 -*-

import time
import numpy as np



print('Start:')
print "Annie is a pig."

# value1 = 'hehe'
# print('value1 = %s', value1)
# print 'value1 = %s' % value1
print '----------------------------------'


def fn(x):
    return x*x


def add(x, y):
    return x + y


def fn1(x, y):
    return x*10+y


def char2num(s):
    return {'0': 0, '1': 1, '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9}[s]


def format_name(s):
    return s[0].upper() + s[1:].lower()


def is_prime(a):
    return


list_num = [1, 3, 5, 7, 9]
name = ['adam', 'LISA', 'barT']

print 'list_num:', list_num
print 'map(str, list_num):', map(str, list_num)
print 'map(fn, list_num):', map(fn, list_num)
print 'reduce(add, list_num):', reduce(add, list_num)
print 'reduce(fn1, list_num):', reduce(fn1, list_num)
print 'char2num:', reduce(fn1, map(char2num, '13579'))
print 'name:', name
print 'map(format_name, name):', map(format_name, name)

kw = {'y': 456, 'x': 123, 'z': 7890, 'hehe': 000}
msg = 'hehe%(y)s'
print msg % kw

a = 3
print 2 ** a

# alist = []
# alist[0] = 0 # alist.append(0)
# print alist

# print time.time()

# x = np.arange(0, 10 + 1)
# print type(x)
# print x

print "--------------------------"
path = ["111", "222", "333", "444", "555"]
print "path[2:3]:", path[2:3]
for i in xrange(0, len(path)-1):
    print path[i]
print "--------------------------"

link_to_port = {(1, 2): ("1-1", "2-1"), (1, 3): ("1-1", "3-1"), (2, 3): ("2-2", "3-2")}
# {(src_dpid,dst_dpid):(src_port,dst_port),}
print link_to_port[(1, 3)][1]
print "--------------------------"

print 7/3
print "--------------------------"
flow=('10.5.0.1', '10.1.0.1', 6, 42226, 5001)
src_ip, dst_ip, L4_Proto, L4_src_port, L4_dst_port = flow
print src_ip, dst_ip, L4_Proto, L4_src_port, L4_dst_port
print "--------------------------"

serversList = set("h00" + str(no) for no in xrange(1, 10)).union(set("h0" + str(no) for no in xrange(10, 17)))
# serversList
print serversList
for it in serversList:
    print it