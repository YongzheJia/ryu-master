
import os
import time
from subprocess import Popen
from multiprocessing import Process
import fattree_only
from ryu.app.exp_BFlows2.BFlows import iperf_peers
from fattree_only import args, FAT_NET, FAT_TOPO, serversList  # traffic_generation,

# k_paths = args.k ** 2 / 8   # We should utilize more paths.
k_paths = args.k ** 2 * 3 / 4
fanout = args.k

# 2. Start the controller.
Popen("ryu-manager --observe-links /home/jyz/ryu-master/ryu/app/exp_BFlows2/BFlows/BFlows.py --k_paths=%d --weight=fnum --fanout=%d" % (k_paths, fanout), shell=True, preexec_fn=os.setsid)

# # Wait until the controller has discovered network topology.
time.sleep(5)

# # 3. Generate traffics and test the performance of the network.
# traffic_generation(FAT_NET, FAT_TOPO, iperf_peers.iperf_peers)
"""
	Generate traffics and test the performance of the network.
"""
# 1. Start iperf. (Elephant flows)
# Start the servers.
# net = FAT_NET
# topo = FAT_TOPO
flows_peers = iperf_peers.iperf_peers

print flows_peers
print serversList
# FAT_NET.build()
# FAT_NET.start()
print FAT_NET.hosts
# serversList = set([peer[1] for peer in flows_peers])
for server in serversList:
    # filename = server[1:]
    server = FAT_NET.get(server)
    print server.__str__()
    # server.cmd("iperf -s > %s/%s &" % (args.output_dir, 'server'+filename+'.txt'))
    server.cmdPrint("iperf -s > /dev/null &")  # Its statistics is useless, just throw away.

time.sleep(3)

# Start the clients.
for src, dest in flows_peers:
    server = FAT_NET.get(dest)
    client = FAT_NET.get(src)
    # filename = src[1:]
    # client.cmd("iperf -c %s -t %d > %s/%s &" % (server.IP(), args.duration, args.output_dir, 'client'+filename+'.txt'))
    client.cmd("iperf -c %s -t %d > /dev/null &" % (server.IP(), 1990))  # Its statistics is useless, just throw away. 1990 just means a great number.
    time.sleep(1)

# Wait for the traffic to become stable.
time.sleep(3)

# 2. Start bwm-ng to monitor throughput.
def monitor_devs_ng(fname="./txrate.txt", interval_sec=0.1):
	"""
		Use bwm-ng tool to collect interface transmit rate statistics.
		bwm-ng Mode: rate;
		interval time: 1s.
	"""
	cmd = "sleep 1; bwm-ng -t %s -o csv -u bits -T rate -C ',' > %s" %  (interval_sec * 1000, fname)
	Popen(cmd, shell=True).wait()


monitor = Process(target=monitor_devs_ng, args=('%s/bwmng.txt' % args.output_dir, 1.0))
monitor.start()

# 3. The experiment is going on.
time.sleep(args.duration + 5)

# 4. Shut down.
monitor.terminate()
os.system('killall bwm-ng')
os.system('killall iperf')
# FAT_NET.stop()

