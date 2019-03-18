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

x = np.arange(0, 10 + 1)
print type(x)
print x