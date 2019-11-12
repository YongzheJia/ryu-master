# Copyright (C) 2016 Huang MaChi at Chongqing University
# of Posts and Telecommunications, Chongqing, China.
# Copyright (C) 2016 Li Cheng at Beijing University of Posts
# and Telecommunications. www.muzixing.com
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import division
import copy
import math
from operator import attrgetter

from ryu import cfg
from ryu.base import app_manager
from ryu.base.app_manager import lookup_service_brick
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib import hub

from ryu.controller import event
# import BFlows

import setting


CONF = cfg.CONF


class EventFlowentryUpdate(event.EventBase):
    def __init__(self, flows):
        super(EventFlowentryUpdate, self).__init__()
        # self.dst = 'shortest_forwarding'
        self.flows = flows


class NetworkMonitor(app_manager.RyuApp):
	"""
		NetworkMonitor is a Ryu app for collecting traffic information.
	"""
	OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

	def __init__(self, *args, **kwargs):
		super(NetworkMonitor, self).__init__(*args, **kwargs)
		self.name = 'monitor'
		self.datapaths = {}
		self.edge_datapaths = {}
		self.core_agg_datapaths = {}
		self.port_stats = {}
		self.port_speed = {}
		self.stats = {}
		self.port_features = {}
		self.flow_num = {}   # self.flow_num = {dpid:{port_no:fnum,},}
		self.free_bandwidth = {}   # self.free_bandwidth = {dpid:{port_no:free_bw,},} unit:Kbit/s
		self.awareness = lookup_service_brick('awareness')
		self.graph = None
		self.best_paths = None
		# self.cur_best_paths = self.awareness.shortest_paths  # store the best_paths in pre_period.
		self.cur_best_paths = None

		# Save ele and mice flow.
		self.CEAED_ele_flows = []
		self.CEAED_ele_flows_each_period = {}
		self.Hedera_ele_flows = []
		self.Hedera_ele_flows_each_period = {}
		self.BFlows_ele_flows = []
		self.Two_ele_flows = []
		self.old_CEAED_ele_flows = []
		self.mice_flows = []
		self.flow_size_per_period = {}
		self.true_total_flow_size = {}
		self.network_traffic = 0
		self.monitor_period = 0

		# Start to green thread to monitor traffic and calculating
		# flow number of links respectively.
		self.monitor_thread = hub.spawn(self._monitor)
		self.save_fnum_thread = hub.spawn(self._save_fnum_graph)

	def _monitor(self):
		"""
			Main entry method of monitoring traffic.
		"""
		while CONF.weight == 'fnum':
			self.stats['port'] = {}

			for dp in self.datapaths.values():
				self.port_features.setdefault(dp.id, {})
				self._request_stats(dp)

			self.monitor_period = (self.monitor_period+1) % 60
			if self.monitor_period in [5, 10, 15, 20, 25, 30, 35, 40]:
				self.calculate_FPR_and_FNR()

			# hub.sleep(setting.MONITOR_PERIOD)

			# Reroute Ele-flow
			if self.CEAED_ele_flows and self.CEAED_ele_flows != self.old_CEAED_ele_flows:
				self.send_event('bflows', EventFlowentryUpdate(self.CEAED_ele_flows), MAIN_DISPATCHER)
				# print "Send event to reroute ele-flows."
				self.old_CEAED_ele_flows = self.CEAED_ele_flows
			# self.old_ele_flows = self.ele_flows
			# self.ele_flows = []

			hub.sleep(setting.MONITOR_PERIOD)

			# print "monitor ele-flows:", self.ele_flows
			# Refresh data.
			self.best_paths = None

			if self.stats['port']:
				self.show_stat()
				hub.sleep(1)

	def calculate_FPR_and_FNR(self):

		total_flow_num = len(self.true_total_flow_size)
		if total_flow_num == 0:
			return
		self.network_traffic = 0
		for flow in self.true_total_flow_size.keys():
			self.network_traffic = self.network_traffic + self.true_total_flow_size[flow]
		# Real elephant flow is defined as the flow that carries traffic exceed
		# 0.1% of the total network traffic.
		Th_true = 0.0001*self.network_traffic
		print "Th_true: ", Th_true/1000000  # MB

		# CEAED
		CEAED_FPR_each_period = []
		CEAED_FNR_each_period = []

		for i in self.CEAED_ele_flows_each_period.keys():
			CEAED_FPR = 0
			CEAED_FNR = 0
			CEAED_FP = 0
			CEAED_FN = 0
			for flow in self.CEAED_ele_flows_each_period[i]:
				if self.true_total_flow_size[flow] < Th_true:
					CEAED_FP += 1
			CEAED_FPR = CEAED_FP / total_flow_num
			CEAED_FPR_each_period.append(CEAED_FPR)

			for flow in self.true_total_flow_size.keys():
				if self.true_total_flow_size[flow] >= Th_true and flow not in self.CEAED_ele_flows_each_period[i]:
					CEAED_FN += 1
			CEAED_FNR = CEAED_FN / total_flow_num
			CEAED_FNR_each_period.append(CEAED_FNR)

		total_periods = len(CEAED_FPR_each_period)
		total_FPR = 0
		total_FNR =0
		Avg_CEAED_FPR = 0
		Avg_CEAED_FNR = 0
		for i in range(0, total_periods):
			total_FPR = total_FPR + CEAED_FPR_each_period[i]
			total_FNR = total_FNR + CEAED_FNR_each_period[i]
		Avg_CEAED_FPR = total_FPR / total_periods
		Avg_CEAED_FNR = total_FNR / total_periods
		print "CEAED: FPR=%s, FNR=%s." % (Avg_CEAED_FPR, Avg_CEAED_FNR)
		print "All FPR and FNR: ", CEAED_FPR_each_period, CEAED_FNR_each_period

		# Hedera
		Hedera_FPR_each_period = []
		Hedera_FNR_each_period = []

		for i in self.Hedera_ele_flows_each_period.keys():
			Hedera_FPR = 0
			Hedera_FNR = 0
			Hedera_FP = 0
			Hedera_FN = 0
			for flow in self.Hedera_ele_flows_each_period[i]:
				if self.true_total_flow_size[flow] < Th_true:
					Hedera_FP += 1
			Hedera_FPR = Hedera_FP / total_flow_num
			Hedera_FPR_each_period.append(Hedera_FPR)

			for flow in self.true_total_flow_size.keys():
				if self.true_total_flow_size[flow] >= Th_true and flow not in self.Hedera_ele_flows_each_period[i]:
					Hedera_FN += 1
			Hedera_FNR = Hedera_FN / total_flow_num
			Hedera_FNR_each_period.append(Hedera_FNR)

		total_periods = len(Hedera_FPR_each_period)
		total_FPR = 0
		total_FNR =0
		Avg_Hedera_FPR = 0
		Avg_Hedera_FNR = 0
		for i in range(0, total_periods):
			total_FPR = total_FPR + Hedera_FPR_each_period[i]
			total_FNR = total_FNR + Hedera_FNR_each_period[i]
		Avg_Hedera_FPR = total_FPR / total_periods
		Avg_Hedera_FNR = total_FNR / total_periods
		print "Hedera: FPR=%s, FNR=%s." % (Avg_Hedera_FPR, Avg_Hedera_FNR)
		print "All FPR and FNR: ", Hedera_FPR_each_period, Hedera_FNR_each_period

		# for flow in self.CEAED_ele_flows:
		# 	if self.total_flow_size[flow] < Th_true:
		# 		CEAED_FP += 1
		# CEAED_FPR = CEAED_FP / total_flow_num
		#
		# for flow in self.total_flow_size.keys():
		# 	if self.total_flow_size[flow] >= Th_true and flow not in self.CEAED_ele_flows:
		# 		CEAED_FN += 1
		# CEAED_FNR = CEAED_FN / total_flow_num
		#
		# print "CEAED: FPR=%s, FNR=%s." % (CEAED_FPR, CEAED_FNR)

	def _save_fnum_graph(self):
		"""
			Save flow number data into networkx graph object.
		"""
		while CONF.weight == 'fnum':
			self.graph = self.create_fnum_graph(self.flow_num)
			self.logger.debug("save flow number")
			self.create_bw_graph(self.graph, self.free_bandwidth)
			self.logger.debug("save free bandwidth")
			hub.sleep(setting.MONITOR_PERIOD)

	@set_ev_cls(ofp_event.EventOFPStateChange,
				[MAIN_DISPATCHER, DEAD_DISPATCHER])
	def _state_change_handler(self, ev):
		"""
			Record datapath information.
		"""
		datapath = ev.datapath
		if ev.state == MAIN_DISPATCHER:
			if not datapath.id in self.datapaths:
				self.logger.debug('register datapath: %016x', datapath.id)
				self.datapaths[datapath.id] = datapath

				# Register edge-switches and other switches.
				if datapath.id > 3000:
					self.edge_datapaths[datapath.id] = datapath
					# print "edge_dp:", datapath.id
				# Register other switches.
				else:
					self.core_agg_datapaths[datapath.id] = datapath

		elif ev.state == DEAD_DISPATCHER:
			if datapath.id in self.datapaths:
				self.logger.debug('unregister datapath: %016x', datapath.id)
				del self.datapaths[datapath.id]

			# delete datapath in edge_datapaths and core_agg_datapaths
			if datapath.id in self.edge_datapaths[datapath.id]:
				del self.edge_datapaths[datapath.id]
			elif datapath.id in self.core_agg_datapaths[datapath.id]:
				del self.core_agg_datapaths[datapath.id]

		else:
			pass

	@set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
	def _flow_stats_reply_handler(self, ev):
		"""
			Calculate flow speed and Save it.
			Note: table-miss, LLDP and ARP flow entries are not what we need, just filter them.
		"""
		body = ev.msg.body

		# Clear ele_flows to save new ele flows.
		# self.old_ele_flows = self.ele_flows
		# self.ele_flows = []

		# We need init flow_num for all of switches.
		# dpid = ev.msg.datapath.id
		# self.flow_num.setdefault(dpid, {})

		for stat in sorted([flow for flow in body if (flow.priority not in [0, 65535])]):

			# Record each flow.
			ip_src = stat.match['ipv4_src']
			ip_dst = stat.match['ipv4_dst']
			L4_Proto = stat.match['ip_proto']
			L4_src_port = stat.match['tcp_src']
			L4_dst_port = stat.match['tcp_dst']
			flow = (ip_src, ip_dst, L4_Proto, L4_src_port, L4_dst_port)
			# if flow not in self.all_flows.keys():
			self.true_total_flow_size[flow] = stat.byte_count

			# CEAED records the flow size in current period.
			if self.flow_size_per_period.has_key(flow):
				self.flow_size_per_period[flow] = stat.byte_count - \
												  self.flow_size_per_period[flow]
			else:
				self.flow_size_per_period[flow] = stat.byte_count

			# Get flow's speed and record it.
			duration = self._get_time(stat.duration_sec, stat.duration_nsec)
			if duration < 0.1:
				duration = 0.1
			speed = float(stat.byte_count) / duration   # unit: byte/s
			_speed = speed * 8.0 / (setting.MAX_CAPACITY * 1000)

			# Ele_flows detection
			is_ele = False

			# Hedera
			self.Hedera_ele_flows = []
			if stat.byte_count > 1000000:  # 1MB
				self.Hedera_ele_flows.append(flow)
			# self.Hedera_ele_flows_each_period[self.monitor_period] = self.Hedera_ele_flows

			# BFlows
			BFlows_is_ele = False
			if _speed >= 0.1:
				BFlows_is_ele = True

			# Two-stage
			Two_is_ele = False
			if stat.byte_count > 1000000 and duration > 1:  # 1MB
				Two_is_ele = True

			# is_ele = Hedera_is_ele
			# if _speed >= 0.1:
			if is_ele:
				# ip_src = stat.match['ipv4_src']
				# ip_dst = stat.match['ipv4_dst']
				# L4_Proto = stat.match['ip_proto']
				# L4_src_port = stat.match['tcp_src']
				# L4_dst_port = stat.match['tcp_dst']
				# flow = (ip_src, ip_dst, L4_Proto, L4_src_port, L4_dst_port)
				# if flow not in self.ele_flows:
				if flow not in self.CEAED_ele_flows:
					self.CEAED_ele_flows.append(flow)
					print "Add a ele-flow:", flow
				# print "All ele-flow:", self.ele_flows

				# Structure of stat
				# print stat
				# OFPFlowStats(byte_count=12894432,cookie=0,duration_nsec=271000000,duration_sec=33,flags=0,
				# hard_timeout=0,idle_timeout=0,
				# instructions=[OFPInstructionActions(actions=[OFPActionOutput(len=16,max_len=65509,port=2,type=0)],len=24,type=4)],length=128,
				# match=OFPMatch(oxm_fields={'ipv4_dst': '10.3.0.1', 'tcp_src': 45274, 'ipv4_src': '10.7.0.1', 'eth_type': 2048, 'tcp_dst': 5001, 'ip_proto': 6, 'in_port': 3}),
				# packet_count=4892,priority=30,table_id=1)

				# Now we have only obtained upload-flow statistics information in edge switches, so we
				# need to calculate up and download-flow statistics information in core and agg switches.
				# In other words, we need calculate the path every flow passed and then update the flow_num
				# in core and agg switches.

				# self._save_fnum(dpid, stat.instructions[0].actions[0].port)

		# CEAED
		flow_num = len(self.flow_size_per_period)
		if flow_num <= 1:
			return
		# flow_size = sorted(self.flow_size_per_period.items(), key=lambda x: x[1], reverse=True)
		flow_size = sorted(self.true_total_flow_size.items(), key=lambda x: x[1], reverse=True)
		# print "flow_size_per_period:", flow_size

		ele_persent = 0.1
		mice_persent = 1 - ele_persent

		ele_num = int(flow_num * ele_persent)
		# Not divide by 0.
		if ele_num is 0:
			ele_num = 1
		mice_num = flow_num - ele_num

		# Calculate dynamic threshold.
		total_ele_size = 0
		for i in range(0, ele_num):
			total_ele_size = total_ele_size + flow_size[i][1] / 1000000  # MB
		mu_ele = total_ele_size / ele_num
		for i in range(0, ele_num):
			temp = (flow_size[i][1]/1000000 - mu_ele) * (flow_size[i][1]/1000000 - mu_ele)  # MB
		sigma_ele = temp / ele_num

		total_mice_size = 0
		for i in range(ele_num+1, flow_num):
			total_mice_size = total_mice_size + flow_size[i][1] / 1000000  # MB
		mu_mice = total_mice_size / mice_num
		for i in range(ele_num+1, flow_num):
			temp = (flow_size[i][1]/1000000 - mu_mice) * (flow_size[i][1]/1000000 - mu_mice)  # MB
		sigma_mice = temp / mice_num

		Th = ((mu_ele*mu_ele-mu_mice*mu_mice) +
			  2*sigma_ele*sigma_ele*math.log(ele_persent/mice_persent))\
			 / 2*(mu_ele-mu_mice)  # MB

		if Th < 0.01:
			Th = 0.01  # 10KB
		print "Th=", Th  # MB

		self.CEAED_ele_flows = []
		for flow in self.flow_size_per_period.keys():
			# if self.flow_size_per_period[flow]/1000000 >= Th:
			if self.flow_size_per_period[flow]/1000000 >= Th/self.monitor_period:
				self.CEAED_ele_flows.append(flow)
		# for flow in self.true_total_flow_size.keys():
		# 	if self.true_total_flow_size[flow]/1000000 >= Th:
		# 		self.CEAED_ele_flows.append(flow)
				# print "CEAED adds a ele-flow:", flow
		self.CEAED_ele_flows_each_period[self.monitor_period] = self.CEAED_ele_flows

		# Hedera
		self.Hedera_ele_flows_each_period[self.monitor_period] = self.Hedera_ele_flows

		# # Calculate the FPR and the FNR of CEAED.
		# total_flow_num = len(self.total_flow_size)
		# self.network_traffic = 0
		# CEAED_FP = 0
		# CEAED_FN = 0
		# CEAED_FPR = 0
		# CEAED_FNR = 0
		#
		# for flow in self.total_flow_size.keys():
		# 	self.network_traffic = self.network_traffic + self.total_flow_size[flow]
		#
		# # Real elephant flow is defined as the flow that carries traffic exceed
		# # 0.1% of the total network traffic.
		# Th_true = 0.001*self.network_traffic
		#
		# for flow in self.ele_flows:
		# 	if self.total_flow_size[flow] < Th_true:
		# 		CEAED_FP += 1
		# CEAED_FPR = CEAED_FP / total_flow_num
		#
		# for flow in self.total_flow_size.keys():
		# 	if self.total_flow_size[flow] >= Th_true and flow not in self.ele_flows:
		# 		CEAED_FN += 1
		# CEAED_FNR = CEAED_FN / total_flow_num
		#
		# print "FPR=%s, FNR=%s." % (CEAED_FPR, CEAED_FNR)

		for flow in self.CEAED_ele_flows:
				# src_ip = stat.match['ipv4_src']
				# dst_ip = stat.match['ipv4_dst']

			src_ip = flow[0]
			dst_ip = flow[1]
			access_table = self.awareness.access_table
			# src_dp = sw[0] for sw in access_table.keys() if access_table[sw][0] == src_ip
			for sw in access_table.keys():
				if access_table[sw][0] == src_ip:
					src_dp = sw[0]
					# print "src_ip,src_dp:", src_ip, src_dp

			for sw in access_table.keys():
				if access_table[sw][0] == dst_ip:
					dst_dp = sw[0]
					# print "dst_ip,dst_dp:", dst_ip, dst_dp

			# Calculate flow_num in core and agg switches.
			# print "cur_best_paths:\n", self.cur_best_paths
			if self.cur_best_paths is None:
				flow_path = self.awareness.shortest_paths.get(src_dp).get(dst_dp)[0]
			else:
				flow_path = self.cur_best_paths.get(src_dp).get(dst_dp)
			# print "Ele_flows %s(%s) to %s(%s) :" % (src_ip, src_dp, dst_ip, dst_dp), flow_path

			# print "try to save flow_num..."
			# print "flow_path:", flow_path
			link_to_port = self.awareness.link_to_port
			# for link, port in link_to_port.items():
			# 	(src_dpid, dst_dpid) = link
			# 	(src_port, dst_port) = port
			if len(flow_path) > 1:
				for i in xrange(0, len(flow_path)-1):
					dpid = flow_path[i]
					next_dpid = flow_path[i+1]
					# print "link_to_port:", link_to_port
					# print "(dpid, next_dpid):", (dpid, next_dpid)
					# print "link_to_port[(dpid, next_dpid)]:", link_to_port[(dpid, next_dpid)]
					port_no = link_to_port[(dpid, next_dpid)][0]
					self.flow_num.setdefault(dpid, {})
					self._save_fnum(dpid, port_no)
					# print "Save flow_num(dpid port_no):", dpid, port_no
		# Update flow entries
		# for flow in self.ele_flows:
		# 	# if flow not in self.old_ele_flows:
		# 	if True:
		# 		# Reroute Ele-flow
		# 		self.send_request(EventFlowentryUpdate(flow))
		# 		print "Send event to reroute ele-flow."
		# for flow in self.old_ele_flows:
		# 	if flow not in self.ele_flows:
		# 		# Reroute Mice-flow
		# 		self.send_request(EventFlowentryUpdate(flow))
		# 		print "Send event to reroute mi-flow."

		# self.old_ele_flows = self.ele_flows
				# try:
				# 	print "try to save flow_num..."
				# 	link_to_port = self.awareness.link_to_port
				# 	# for link, port in link_to_port.items():
				# 	# 	(src_dpid, dst_dpid) = link
				# 	# 	(src_port, dst_port) = port
				# 	if len(flow_path) > 1:
				# 		for i in xrange(0, len(flow_path)-1):
				# 			dpid = flow_path[i]
				# 			next_dpid = flow_path[i+1]
				# 			port_no = link_to_port[(dpid, next_dpid)][0]
				# 			self._save_fnum(dpid, port_no)
				# 			print "Save flow_num(dpid port_no):", dpid, port_no
				#
				# except:
				# 	self.logger.info("Save flow exception")
				# 	if self.awareness is None:
				# 		self.awareness = lookup_service_brick('awareness')

				# self._save_fnum(dpid, stat.instructions[0].actions[0].port)

				# print "ele_flows from %s:" %dpid, stat.instructions[0].actions[0]

	@set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
	def _port_stats_reply_handler(self, ev):
		"""
			Save port's stats information into self.port_stats.
			Calculate port speed and Save it.
			self.port_stats = {(dpid, port_no):[(tx_bytes, rx_bytes, rx_errors, duration_sec,  duration_nsec),],}
			self.port_speed = {(dpid, port_no):[speed,],}
			Note: The transmit performance and receive performance are independent of a port.
			We calculate the load of a port only using tx_bytes.
		"""
		body = ev.msg.body
		dpid = ev.msg.datapath.id
		self.stats['port'][dpid] = body
		self.free_bandwidth.setdefault(dpid, {})

		for stat in sorted(body, key=attrgetter('port_no')):
			port_no = stat.port_no
			if port_no != ofproto_v1_3.OFPP_LOCAL:
				key = (dpid, port_no)
				value = (stat.tx_bytes, stat.rx_bytes, stat.rx_errors,
						 stat.duration_sec, stat.duration_nsec)
				self._save_stats(self.port_stats, key, value, 5)

				# Get port speed and Save it.
				pre = 0
				period = setting.MONITOR_PERIOD
				tmp = self.port_stats[key]
				if len(tmp) > 1:
					# Calculate only the tx_bytes, not the rx_bytes. (hmc)
					pre = tmp[-2][0]
					period = self._get_period(tmp[-1][3], tmp[-1][4], tmp[-2][3], tmp[-2][4])
				speed = self._get_speed(self.port_stats[key][-1][0], pre, period)
				self._save_stats(self.port_speed, key, speed, 5)
				self._save_freebandwidth(dpid, port_no, speed)

	@set_ev_cls(ofp_event.EventOFPPortDescStatsReply, MAIN_DISPATCHER)
	def port_desc_stats_reply_handler(self, ev):
		"""
			Save port description info.
		"""
		msg = ev.msg
		dpid = msg.datapath.id
		ofproto = msg.datapath.ofproto

		config_dict = {ofproto.OFPPC_PORT_DOWN: "Down",
					   ofproto.OFPPC_NO_RECV: "No Recv",
					   ofproto.OFPPC_NO_FWD: "No Farward",
					   ofproto.OFPPC_NO_PACKET_IN: "No Packet-in"}

		state_dict = {ofproto.OFPPS_LINK_DOWN: "Down",
					  ofproto.OFPPS_BLOCKED: "Blocked",
					  ofproto.OFPPS_LIVE: "Live"}

		ports = []
		for p in ev.msg.body:
			ports.append('port_no=%d hw_addr=%s name=%s config=0x%08x '
						 'state=0x%08x curr=0x%08x advertised=0x%08x '
						 'supported=0x%08x peer=0x%08x curr_speed=%d '
						 'max_speed=%d' %
						 (p.port_no, p.hw_addr,
						  p.name, p.config,
						  p.state, p.curr, p.advertised,
						  p.supported, p.peer, p.curr_speed,
						  p.max_speed))

			if p.config in config_dict:
				config = config_dict[p.config]
			else:
				config = "up"

			if p.state in state_dict:
				state = state_dict[p.state]
			else:
				state = "up"

			# Recording data.
			port_feature = (config, state, p.curr_speed)
			self.port_features[dpid][p.port_no] = port_feature

	@set_ev_cls(ofp_event.EventOFPPortStatus, MAIN_DISPATCHER)
	def _port_status_handler(self, ev):
		"""
			Handle the port status changed event.
		"""
		msg = ev.msg
		ofproto = msg.datapath.ofproto
		reason = msg.reason
		dpid = msg.datapath.id
		port_no = msg.desc.port_no

		reason_dict = {ofproto.OFPPR_ADD: "added",
					   ofproto.OFPPR_DELETE: "deleted",
					   ofproto.OFPPR_MODIFY: "modified", }

		if reason in reason_dict:
			print "switch%d: port %s %s" % (dpid, reason_dict[reason], port_no)
		else:
			print "switch%d: Illeagal port state %s %s" % (dpid, port_no, reason)

	def _request_stats(self, datapath):
		"""
			Sending request msg to datapath
		"""
		self.logger.debug('send stats request: %016x', datapath.id)
		ofproto = datapath.ofproto
		parser = datapath.ofproto_parser
		req = parser.OFPPortDescStatsRequest(datapath, 0)
		datapath.send_msg(req)
		req = parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
		datapath.send_msg(req)

		# only monitor flow statistics information in edge_datapaths
		# print "to send flow_stats_request..."
		if datapath.id in self.edge_datapaths.keys():
			# req = parser.OFPFlowStatsRequest(datapath)
			tid_mnt = 1
			req = parser.OFPFlowStatsRequest(datapath=datapath, table_id=tid_mnt)
			datapath.send_msg(req)
			# print "send flow_stats to:", datapath.id

	def get_max_fnum_of_links(self, graph, path, max_fnum):
		"""
			Get flow number of path.
		"""
		_len = len(path)
		if _len > 1:
			max_flownum = max_fnum
			for i in xrange(_len-1):
				pre, curr = path[i], path[i+1]
				if 'fnum' in graph[pre][curr]:
					_fnum = graph[pre][curr]['fnum']
					max_flownum = max(_fnum, max_flownum)
				else:
					continue
			return max_flownum
		else:
			return max_fnum

	def get_min_bw_of_links(self, graph, path, min_bw):
		"""
			Getting bandwidth of path. Actually, the mininum bandwidth
			of links is the path's bandwith, because it is the bottleneck of path.
		"""
		_len = len(path)
		if _len > 1:
			minimal_band_width = min_bw
			for i in xrange(_len-1):
				pre, curr = path[i], path[i+1]
				if 'bandwidth' in graph[pre][curr]:
					bw = graph[pre][curr]['bandwidth']
					minimal_band_width = min(bw, minimal_band_width)
				else:
					continue
			return minimal_band_width
		else:
			return min_bw

	def get_best_path_by_fnum(self, graph, paths):
		"""
			Get best path by comparing paths.
			Note: This function is called in BFlows module.
		"""
		best_paths = copy.deepcopy(paths)
		fnum_of_paths = copy.deepcopy(paths)

		# Reset the fnum_of_paths data structure.
		for src in fnum_of_paths.keys():
			for dst in fnum_of_paths[src].keys():
				fnum_of_paths[src][dst] = {}

		# Calculate the flow number of each path and save it.
		for src in paths:
			for dst in paths[src]:
				if src == dst:
					best_paths[src][src] = [src]
				else:
					for path in paths[src][dst]:
						max_fnum = 0
						max_fnum = self.get_max_fnum_of_links(graph, path, max_fnum)
						fnum_of_paths[src][dst].setdefault(max_fnum, [])
						fnum_of_paths[src][dst][max_fnum].append(path)

					# Get the least flow number paths and find the lightest-load one of them.
					min_fnum = min(fnum_of_paths[src][dst].keys())
					max_bw_of_paths = 0
					best_path = fnum_of_paths[src][dst][min_fnum][0]
					for path in fnum_of_paths[src][dst][min_fnum]:
						min_bw = setting.MAX_CAPACITY
						min_bw = self.get_min_bw_of_links(graph, path, min_bw)
						if min_bw > max_bw_of_paths:
							max_bw_of_paths = min_bw
							best_path = path
					best_paths[src][dst] = best_path

		self.best_paths = best_paths
		# Save the best paths to avoid it to be refreshed.
		self.cur_best_paths = best_paths
		return best_paths

	def zero_dictionary(self, fnum_dict):
		for sw in fnum_dict.keys():
			for port in fnum_dict[sw].keys():
				fnum_dict[sw][port] = 0

	def create_fnum_graph(self, fnum_dict):
		"""
			Save flow number data into networkx graph object.
			self.flow_num = {dpid:{port_no:fnum,},}
		"""
		try:
			graph = self.awareness.graph
			link_to_port = self.awareness.link_to_port
			for link, port in link_to_port.items():
				(src_dpid, dst_dpid) = link
				(src_port, dst_port) = port
				if fnum_dict.has_key(src_dpid) and fnum_dict[src_dpid].has_key(src_port):
					fnum = fnum_dict[src_dpid][src_port]
					# Add key-value pair of flow number into graph.
					if graph.has_edge(src_dpid, dst_dpid):
						graph[src_dpid][dst_dpid]['fnum'] = fnum
					else:
						graph.add_edge(src_dpid, dst_dpid)
						graph[src_dpid][dst_dpid]['fnum'] = fnum
				else:
					if graph.has_edge(src_dpid, dst_dpid):
						graph[src_dpid][dst_dpid]['fnum'] = 0
					else:
						graph.add_edge(src_dpid, dst_dpid)
						graph[src_dpid][dst_dpid]['fnum'] = 0
			# print 'fnum_dict:', fnum_dict
			# Zero the flow_num dictionary.
			self.zero_dictionary(fnum_dict)
			return graph
		except:
			self.logger.info("Create flow number graph exception")
			if self.awareness is None:
				self.awareness = lookup_service_brick('awareness')
			# print 'fnum_dict:', fnum_dict
			# Zero the flow_num dictionary.
			self.zero_dictionary(fnum_dict)
			return self.awareness.graph

	def _save_fnum(self, dpid, port_no):
	# def _save_fnum(self, dpid, port_no, src, dst):
		"""
			Record flow number of port.
			port_feature = (config, state, p.curr_speed)
			self.port_features[dpid][p.port_no] = port_feature
			self.flow_num = {dpid:{port_no:num,},}
		"""




		port_state = self.port_features.get(dpid).get(port_no)
		if port_state:
			self.flow_num[dpid].setdefault(port_no, 0)
			self.flow_num[dpid][port_no] += 1
		else:
			self.logger.info("Port is Down")

	def create_bw_graph(self, graph, bw_dict):
		"""
			Save bandwidth data into networkx graph object.
		"""
		try:
			link_to_port = self.awareness.link_to_port
			for link, port in link_to_port.items():
				(src_dpid, dst_dpid) = link
				(src_port, dst_port) = port
				if src_dpid in bw_dict and dst_dpid in bw_dict:
					bandwidth = bw_dict[src_dpid][src_port]
					# Add key-value pair of bandwidth into graph.
					if graph.has_edge(src_dpid, dst_dpid):
						graph[src_dpid][dst_dpid]['bandwidth'] = bandwidth
					else:
						graph.add_edge(src_dpid, dst_dpid)
						graph[src_dpid][dst_dpid]['bandwidth'] = bandwidth
				else:
					if graph.has_edge(src_dpid, dst_dpid):
						graph[src_dpid][dst_dpid]['bandwidth'] = 0
					else:
						graph.add_edge(src_dpid, dst_dpid)
						graph[src_dpid][dst_dpid]['bandwidth'] = 0
		except:
			self.logger.info("Create bw graph exception")
			if self.awareness is None:
				self.awareness = lookup_service_brick('awareness')

	def _save_freebandwidth(self, dpid, port_no, speed):
		"""
			Calculate free bandwidth of port and Save it.
			port_feature = (config, state, p.curr_speed)
			self.port_features[dpid][p.port_no] = port_feature
			self.free_bandwidth = {dpid:{port_no:free_bw,},}
		"""
		port_state = self.port_features.get(dpid).get(port_no)
		if port_state:
			capacity = 10000   # The true bandwidth of link, instead of 'curr_speed'.
			free_bw = self._get_free_bw(capacity, speed)
			self.free_bandwidth[dpid].setdefault(port_no, None)
			self.free_bandwidth[dpid][port_no] = free_bw
		else:
			self.logger.info("Port is Down")

	def _save_stats(self, _dict, key, value, length=5):
		if key not in _dict:
			_dict[key] = []
		_dict[key].append(value)
		if len(_dict[key]) > length:
			_dict[key].pop(0)

	def _get_free_bw(self, capacity, speed):
		# freebw: Kbit/s
		return max(capacity - speed * 8 / 1000.0, 0)

	def _get_speed(self, now, pre, period):
		if period:
			return (now - pre) / (period)
		else:
			return 0

	def _get_time(self, sec, nsec):
		return sec + nsec / 1000000000.0

	def _get_period(self, n_sec, n_nsec, p_sec, p_nsec):
		return self._get_time(n_sec, n_nsec) - self._get_time(p_sec, p_nsec)

	def show_stat(self):
		'''
			Show statistics information.
		'''
		if setting.TOSHOW is False:
			return

		bodys = self.stats['port']
		print('\ndatapath  port '
			'   rx-pkts     rx-bytes ''   tx-pkts     tx-bytes '
			' port-bw(Kb/s)  port-speed(b/s)  port-freebw(Kb/s) '
			' port-state  link-state')
		print('--------  ----  '
			'---------  -----------  ''---------  -----------  '
			'-------------  ---------------  -----------------  '
			'----------  ----------')
		_format = '%8d  %4x  %9d  %11d  %9d  %11d  %13d  %15.1f  %17.1f  %10s  %10s'
		for dpid in sorted(bodys.keys()):
			for stat in sorted(bodys[dpid], key=attrgetter('port_no')):
				if stat.port_no != ofproto_v1_3.OFPP_LOCAL:
					print(_format % (
						dpid, stat.port_no,
						stat.rx_packets, stat.rx_bytes,
						stat.tx_packets, stat.tx_bytes,
						setting.MAX_CAPACITY,
						abs(self.port_speed[(dpid, stat.port_no)][-1] * 8),
						self.free_bandwidth[dpid][stat.port_no],
						self.port_features[dpid][stat.port_no][0],
						self.port_features[dpid][stat.port_no][1]))
		print