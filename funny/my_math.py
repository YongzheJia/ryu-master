import math


def is_prime(x):

    if x == 2 or x == 3:
        return True

    if x % 6 == 1 or x % 6 == 5:
        for y in range(2, int(math.sqrt(x))):
            if x % y == 0:
                return False
        return True

    return False


# num = input('Input number:')
# print is_prime(num)

account = input('Input Account:')
a_list = range(2, account + 1)
print filter(is_prime, a_list)
