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

from ryu import cfg
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import set_ev_cls, set_ev_handler
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import arp
from ryu.lib.packet import ipv4
from ryu.lib.packet import tcp
from ryu.lib.packet import udp

import network_awareness
import network_monitor
import setting


CONF = cfg.CONF


class ShortestForwarding(app_manager.RyuApp):
	"""
		ShortestForwarding is a Ryu app for forwarding packets on shortest path.
		This App does not defined the path computation method.
		To get shortest path, this module depends on network awareness and
		network monitor modules.
	"""

	OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
	_CONTEXTS = {
		"network_awareness": network_awareness.NetworkAwareness,
		"network_monitor": network_monitor.NetworkMonitor}

	WEIGHT_MODEL = {'hop': 'weight', 'fnum': 'fnum'}

	def __init__(self, *args, **kwargs):
		super(ShortestForwarding, self).__init__(*args, **kwargs)
		self.name = "bflows"
		self.awareness = kwargs["network_awareness"]
		self.monitor = kwargs["network_monitor"]
		self.datapaths = {}
		self.weight = self.WEIGHT_MODEL[CONF.weight]
		self.cur_ele_flows = []

	@set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
	def _state_change_handler(self, ev):
		"""
			Collect datapath information.
		"""
		datapath = ev.datapath
		if ev.state == MAIN_DISPATCHER:
			if not datapath.id in self.datapaths:
				self.logger.debug('register datapath: %016x', datapath.id)
				self.datapaths[datapath.id] = datapath
		elif ev.state == DEAD_DISPATCHER:
			if datapath.id in self.datapaths:
				self.logger.debug('unregister datapath: %016x', datapath.id)
				del self.datapaths[datapath.id]

	@set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
	def _packet_in_handler(self, ev):
		'''
			In packet_in handler, we need to learn access_table by ARP and IP packets.
		'''
		msg = ev.msg
		pkt = packet.Packet(msg.data)
		arp_pkt = pkt.get_protocol(arp.arp)
		ip_pkt = pkt.get_protocol(ipv4.ipv4)

		# Parser tcp/udp information for differentiate elephant flow and mice flow.
		tcp_pkt = pkt.get_protocol(tcp.tcp)
		udp_pkt = pkt.get_protocol(udp.udp)

		if isinstance(arp_pkt, arp.arp):
			self.logger.debug("ARP processing")
			self.arp_forwarding(msg, arp_pkt.src_ip, arp_pkt.dst_ip)

		if isinstance(ip_pkt, ipv4.ipv4):
			self.logger.debug("IPV4 processing")
			if len(pkt.get_protocols(ethernet.ethernet)):
				eth_type = pkt.get_protocols(ethernet.ethernet)[0].ethertype
				# print eth_type

				# Forwarding elephant/mice flow.
				if isinstance(tcp_pkt, tcp.tcp):
					self.logger.debug("TCP processing")
					self.shortest_forwarding(msg, eth_type, ip_pkt.src, ip_pkt.dst,
											 L4_Proto=6, L4_src_port=tcp_pkt.src_port, L4_dst_port=tcp_pkt.dst_port)

				elif isinstance(udp_pkt, udp.udp):
					self.logger.debug("UDP processing")
					self.shortest_forwarding(msg, eth_type, ip_pkt.src, ip_pkt.dst,
											 L4_Proto=17, L4_src_port=udp_pkt.src_port, L4_dst_port=udp_pkt.dst_port)

				# Forwarding flow by default.
				else:
					self.shortest_forwarding(msg, eth_type, ip_pkt.src, ip_pkt.dst)

	def add_flow(self, dp, priority, match, actions, idle_timeout=0, hard_timeout=0):
		"""
			Send a flow entry to datapath.
		"""
		ofproto = dp.ofproto
		parser = dp.ofproto_parser
		inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
		tid_mnt = 1

		mod = parser.OFPFlowMod(datapath=dp, table_id=tid_mnt, priority=priority,
								idle_timeout=idle_timeout,
								hard_timeout=hard_timeout,
								match=match, instructions=inst)
		dp.send_msg(mod)

	def _build_packet_out(self, datapath, buffer_id, src_port, dst_port, data):
		"""
			Build packet out object.
		"""
		if buffer_id is None:
			buffer_id = datapath.ofproto.OFP_NO_BUFFER

		actions = []
		if dst_port:
			actions.append(datapath.ofproto_parser.OFPActionOutput(dst_port))

		msg_data = None
		if buffer_id == datapath.ofproto.OFP_NO_BUFFER:
			if data is None:
				return None
			msg_data = data

		out = datapath.ofproto_parser.OFPPacketOut(
			datapath=datapath, buffer_id=buffer_id,
			data=msg_data, in_port=src_port, actions=actions)
		return out

	def send_packet_out(self, datapath, buffer_id, src_port, dst_port, data):
		"""
			Send packet out packet to assigned datapath.
		"""
		out = self._build_packet_out(datapath, buffer_id,
									 src_port, dst_port, data)
		if out:
			datapath.send_msg(out)

	def get_port(self, dst_ip, access_table):
		"""
			Get access port of dst host.
			access_table = {(sw,port):(ip, mac),}
		"""
		if access_table:
			if isinstance(access_table.values()[0], tuple):
				for key in access_table.keys():
					if dst_ip == access_table[key][0]:   # Use the IP address only, not the MAC address. (hmc)
						dst_port = key[1]
						return dst_port
		return None

	def get_port_pair_from_link(self, link_to_port, src_dpid, dst_dpid):
		"""
			Get port pair of link, so that controller can install flow entry.
			link_to_port = {(src_dpid,dst_dpid):(src_port,dst_port),}
		"""
		if (src_dpid, dst_dpid) in link_to_port:
			return link_to_port[(src_dpid, dst_dpid)]
		else:
			self.logger.info("Link from dpid:%s to dpid:%s is not in links" %
			 (src_dpid, dst_dpid))
			return None

	def flood(self, msg):
		"""
			Flood packet to the access ports which have no record of host.
			access_ports = {dpid:set(port_num,),}
			access_table = {(sw,port):(ip, mac),}
		"""
		datapath = msg.datapath
		ofproto = datapath.ofproto

		for dpid in self.awareness.access_ports:
			for port in self.awareness.access_ports[dpid]:
				if (dpid, port) not in self.awareness.access_table.keys():
					datapath = self.datapaths[dpid]
					out = self._build_packet_out(
						datapath, ofproto.OFP_NO_BUFFER,
						ofproto.OFPP_CONTROLLER, port, msg.data)
					datapath.send_msg(out)
		self.logger.debug("Flooding packet to access port")

	def arp_forwarding(self, msg, src_ip, dst_ip):
		"""
			Send ARP packet to the destination host if the dst host record
			is existed, else flow it to the unknow access port.
			result = (datapath, port)
		"""
		datapath = msg.datapath
		ofproto = datapath.ofproto

		result = self.awareness.get_host_location(dst_ip)
		if result:
			# Host has been recorded in access table.
			datapath_dst, out_port = result[0], result[1]
			datapath = self.datapaths[datapath_dst]
			out = self._build_packet_out(datapath, ofproto.OFP_NO_BUFFER,
										 ofproto.OFPP_CONTROLLER,
										 out_port, msg.data)
			datapath.send_msg(out)
			self.logger.debug("Deliver ARP packet to knew host")
		else:
			# Flood is not good.
			self.flood(msg)

	def get_path(self, src, dst, L4_Proto=None, L4_src_port=None, L4_dst_port=None, weight='fnum'):
		"""
			Get shortest path from network_awareness module.
			generator (nx.shortest_simple_paths( )) produces
			lists of simple paths, in order from shortest to longest.
		"""
		shortest_paths = self.awareness.shortest_paths
		graph = self.awareness.graph

		flow = (src, dst, L4_Proto, L4_src_port, L4_dst_port)

		# Mice flow will be forwarded by shortest path.
		if weight == self.WEIGHT_MODEL['hop']:
			# print "Forward flow by hop:", flow
			return shortest_paths.get(src).get(dst)[0]

		elif weight == self.WEIGHT_MODEL['fnum']:
			# print "Forward flow by fnum:", flow
			# Because all paths will be calculated when we call self.monitor.get_best_path_by_fnum,
			# so we just need to call it once in a period, and then, we can get path directly.
			# If path is existed just return it, else calculate and return it.
			try:
				path = self.monitor.best_paths.get(src).get(dst)
				return path
			except:
				result = self.monitor.get_best_path_by_fnum(graph, shortest_paths)
				paths = result
				best_path = paths.get(src).get(dst)
				return best_path
		else:
			pass

	def get_sw(self, dpid, in_port, src, dst):
		"""
			Get pair of source and destination switches.
		"""
		src_sw = dpid
		dst_sw = None
		src_location = self.awareness.get_host_location(src)   # src_location = (dpid, port)
		if in_port in self.awareness.access_ports[dpid]:
			if (dpid, in_port) == src_location:
				src_sw = src_location[0]
			else:
				return None
		dst_location = self.awareness.get_host_location(dst)   # dst_location = (dpid, port)
		if dst_location:
			dst_sw = dst_location[0]
		if src_sw and dst_sw:
			return src_sw, dst_sw
		else:
			return None

	def send_flow_mod(self, datapath, flow_info, src_port, dst_port):
		"""
			Build flow entry, and send it to datapath.
			flow_info = (eth_type, src_ip, dst_ip, in_port)
			or
			flow_info = (eth_type, src_ip, dst_ip, in_port, ip_proto, Flag, L4_port)

			or my definition:
			flow_info = (eth_type, src_ip, dst_ip, in_port, L4_Proto, L4_src_port, L4_dst_port)
			Where L4_Proto equals to ip_proto, and 'in_port' in flow_info equals to 'src_port' in send_flow_mod.
		"""
		parser = datapath.ofproto_parser
		actions = []
		actions.append(parser.OFPActionOutput(dst_port))
		if len(flow_info) == 7:
			# We need new process to build match.

			# if flow_info[-3] == 6:
			# 	if flow_info[-2] == 'src':
			# 		match = parser.OFPMatch(
			# 			in_port=src_port, eth_type=flow_info[0],
			# 			ipv4_src=flow_info[1], ipv4_dst=flow_info[2],
			# 			ip_proto=6, tcp_src=flow_info[-1])
			# 	elif flow_info[-2] == 'dst':
			# 		match = parser.OFPMatch(
			# 			in_port=src_port, eth_type=flow_info[0],
			# 			ipv4_src=flow_info[1], ipv4_dst=flow_info[2],
			# 			ip_proto=6, tcp_dst=flow_info[-1])
			# 	else:
			# 		pass
			# elif flow_info[-3] == 17:
			# 	if flow_info[-2] == 'src':
			# 		match = parser.OFPMatch(
			# 			in_port=src_port, eth_type=flow_info[0],
			# 			ipv4_src=flow_info[1], ipv4_dst=flow_info[2],
			# 			ip_proto=17, udp_src=flow_info[-1])
			# 	elif flow_info[-2] == 'dst':
			# 		match = parser.OFPMatch(
			# 			in_port=src_port, eth_type=flow_info[0],
			# 			ipv4_src=flow_info[1], ipv4_dst=flow_info[2],
			# 			ip_proto=17, udp_dst=flow_info[-1])
			# 	else:
			# 		pass

			# Build match field of TCP flow entry.
			if flow_info[-3] == 6:
				if flow_info[-2] is not None and flow_info[-1] is not None:
					match = parser.OFPMatch(
								in_port=src_port, eth_type=flow_info[0],
								ipv4_src=flow_info[1], ipv4_dst=flow_info[2],
								ip_proto=6, tcp_src=flow_info[-2], tcp_dst=flow_info[-1])
				else:
					pass
			# Build match field of UDP flow entry.
			elif flow_info[-3] == 17:
				if flow_info[-2] is not None and flow_info[-1] is not None:
					match = parser.OFPMatch(
								in_port=src_port, eth_type=flow_info[0],
								ipv4_src=flow_info[1], ipv4_dst=flow_info[2],
								ip_proto=17, udp_src=flow_info[-2], udp_dst=flow_info[-1])
				else:
					pass

		elif len(flow_info) == 4:
			match = parser.OFPMatch(
						in_port=src_port, eth_type=flow_info[0],
						ipv4_src=flow_info[1], ipv4_dst=flow_info[2])
		else:
			pass

		# self.add_flow(datapath, 30, match, actions,
		# 			  idle_timeout=5, hard_timeout=0)
		self.add_flow(datapath, 30, match, actions,
					  idle_timeout=0, hard_timeout=0)

	def install_flow(self, datapaths, link_to_port, path, flow_info, buffer_id, data=None):
		'''
			Install flow entries for datapaths.
			path=[dpid1, dpid2, ...]
			flow_info = (eth_type, src_ip, dst_ip, in_port)
			or
			flow_info = (eth_type, src_ip, dst_ip, in_port, ip_proto, Flag, L4_port)

			or my definition:
			flow_info = (eth_type, src_ip, dst_ip, in_port, L4_Proto, L4_src_port, L4_dst_port)
			Where L4_Proto equals to ip_proto.
		'''
		if path is None or len(path) == 0:
			self.logger.info("Path error!")
			return
		in_port = flow_info[3]
		first_dp = datapaths[path[0]]
		out_port = first_dp.ofproto.OFPP_LOCAL

		# Install flow entry for intermediate datapaths.
		for i in xrange(1, len(path) - 2):
			port = self.get_port_pair_from_link(link_to_port, path[i-1], path[i])
			port_next = self.get_port_pair_from_link(link_to_port, path[i], path[i+1])
			if port and port_next:
				src_port, dst_port = port[1], port_next[0]
				datapath = datapaths[path[i]]
				# Only install flow entry for edge and aggregate switches.
				# TODO: We need install both ele- and mice-flow entries for edge switches,
				#  		but only ele-flow entries for aggregate switches.
				if datapath.id > 2000:
					self.send_flow_mod(datapath, flow_info, src_port, dst_port)

		# Install flow entry for the first datapath.
		# First switches must be edge switch.
		port_pair = self.get_port_pair_from_link(link_to_port, path[0], path[1])
		if port_pair is None:
			self.logger.info("Port not found in first hop.")
			return
		out_port = port_pair[0]
		self.send_flow_mod(first_dp, flow_info, in_port, out_port)
		# Send packet_out to the first datapath.
		self.send_packet_out(first_dp, buffer_id, in_port, out_port, data)

	def get_L4_info(self, tcp_pkt, udp_pkt):
		"""
			Get ip_proto and L4 port number.
		"""
		ip_proto = None
		L4_port = None
		Flag = None
		if tcp_pkt:
			ip_proto = 6
			if tcp_pkt.src_port and tcp_pkt.src_port in setting.bw_sensitive_port_list:
				L4_port = tcp_pkt.src_port
				Flag = 'src'
			elif tcp_pkt.dst_port and tcp_pkt.dst_port in setting.bw_sensitive_port_list:
				L4_port = tcp_pkt.dst_port
				Flag = 'dst'
			else:
				pass
		elif udp_pkt:
			ip_proto = 17
			if udp_pkt.src_port and udp_pkt.src_port in setting.bw_sensitive_port_list:
				L4_port = udp_pkt.src_port
				Flag = 'src'
			elif udp_pkt.dst_port and udp_pkt.dst_port in setting.bw_sensitive_port_list:
				L4_port = udp_pkt.dst_port
				Flag = 'dst'
			else:
				pass
		else:
			pass
		return (ip_proto, L4_port, Flag)

	def shortest_forwarding(self, msg, eth_type, ip_src, ip_dst, L4_Proto=None, L4_src_port=None, L4_dst_port=None):
		"""
			Calculate shortest forwarding path and Install them into datapaths.
			flow_info = (eth_type, ip_src, ip_dst, in_port)
			or
			flow_info = (eth_type, ip_src, ip_dst, in_port, ip_proto, Flag, L4_port)

			or my definition:
			flow_info = (eth_type, src_ip, dst_ip, in_port, L4_Proto, L4_src_port, L4_dst_port)
			Where L4_Proto equals to ip_proto.
		"""
		datapath = msg.datapath
		in_port = msg.match['in_port']
		# Get the first and the last switch attached to src and dst hosts.
		result = self.get_sw(datapath.id, in_port, ip_src, ip_dst)   # result = (src_sw, dst_sw) src_sw = (sw,port)
		# print "result:", result
		flow = (ip_src, ip_dst, L4_Proto, L4_src_port, L4_dst_port)
		# print "flow:", flow
		if result:
			src_sw, dst_sw = result[0], result[1]
			if dst_sw:
				# Path has already been calculated, just get it.
				if L4_Proto is None:
					# Shortest forwarding by default.
					# print "a pkt without L4_Proto"
					path = self.get_path(src_sw, dst_sw, weight=self.WEIGHT_MODEL['hop'])
					self.logger.info("[PATH]%s<-->%s: %s"
									 % (ip_src, ip_dst, path))
					flow_info = (eth_type, ip_src, ip_dst, in_port)
				else:
					# We need pass L4 port information to get_path for path selection
					# print "a pkt with L4_Proto"

					# Elephant flow timeout
					if flow in self.cur_ele_flows:
						path = self.get_path(src_sw, dst_sw, L4_Proto, L4_src_port, L4_dst_port,
											 weight=self.WEIGHT_MODEL['fnum'])
						self.logger.info("[ELE-PATH]%s<-->%s: %s, ip proto:%s, from %s to %s."
										 % (ip_src, ip_dst, path, L4_Proto, L4_src_port, L4_dst_port))
						flow_info = (eth_type, ip_src, ip_dst, in_port, L4_Proto, L4_src_port, L4_dst_port)
					# Mice flow
					else:
						path = self.get_path(src_sw, dst_sw, L4_Proto, L4_src_port, L4_dst_port,
											 weight=self.WEIGHT_MODEL['hop'])
						self.logger.info("[MI-PATH]%s<-->%s: %s, ip proto:%s, from %s to %s."
										 % (ip_src, ip_dst, path, L4_Proto, L4_src_port, L4_dst_port))
						flow_info = (eth_type, ip_src, ip_dst, in_port, L4_Proto, L4_src_port, L4_dst_port)

				# if setting.enable_Flow_Entry_L4Port:
				# 	pkt = packet.Packet(msg.data)
				# 	tcp_pkt = pkt.get_protocol(tcp.tcp)
				# 	udp_pkt = pkt.get_protocol(udp.udp)
				# 	# Get ip_proto and L4 port number.
				# 	ip_proto, L4_port, Flag = self.get_L4_info(tcp_pkt, udp_pkt)
				# 	if ip_proto and L4_port and Flag:
				# 		if ip_proto == 6:
				# 			L4_Proto = 'TCP'
				# 		elif ip_proto == 17:
				# 			L4_Proto = 'UDP'
				# 		else:
				# 			pass
				# 		self.logger.info("[PATH]%s<-->%s(%s Port:%d): %s" % (ip_src, ip_dst, L4_Proto, L4_port, path))
				# 		flow_info = (eth_type, ip_src, ip_dst, in_port, ip_proto, Flag, L4_port)
				#
				# else:
					# Log more information.
					# We need install flow contained L4 port information.


					# if L4_Proto is not None:
					# 	self.logger.info("[PATH]%s<-->%s: %s, ip proto:%s, from %s to %s."
					# 					 % (ip_src, ip_dst, path, L4_Proto, L4_src_port, L4_dst_port))
					# 	flow_info = (eth_type, ip_src, ip_dst, in_port, L4_Proto, L4_src_port, L4_dst_port)
					# else:
					# 	self.logger.info("[PATH]%s<-->%s: %s"
					# 					 % (ip_src, ip_dst, path))
					# 	flow_info = (eth_type, ip_src, ip_dst, in_port)

				# Install flow entries to datapaths along the path.
				self.install_flow(self.datapaths, self.awareness.link_to_port,
								  path, flow_info, msg.buffer_id, msg.data)
		else:
			# Flood is not good.
			self.flood(msg)

	@set_ev_cls(network_monitor.EventFlowentryUpdate, [MAIN_DISPATCHER])
	def update_flow_entries(self, ev):
		"""
			Update flow entries for ele-flows.
			This function will be called by "network_monitor.py".
		"""
		# print "BFlows received EventFlowentryUpdate."
		flows = ev.flows

		# Reroute new ele flows.
		for flow in flows:
			if flow not in self.cur_ele_flows:
				src_ip, dst_ip, L4_Proto, L4_src_port, L4_dst_port = flow
				# Get src and dst switches.
				src_location = self.awareness.get_host_location(src_ip)   # src_location = (dpid, port)
				if src_location:
					src_sw = src_location[0]
				else:
					print "src_sw not found!"
					pass
				dst_location = self.awareness.get_host_location(dst_ip)   # dst_location = (dpid, port)
				if dst_location:
					dst_sw = dst_location[0]
				else:
					print "dst_sw not found!"
					pass

				# print "Reroute ele-flow:", flow
				path = self.get_path(src_sw, dst_sw, L4_Proto, L4_src_port, L4_dst_port,
									 weight=self.WEIGHT_MODEL['fnum'])
				self.logger.info("[RR-ELE-PATH]%s<-->%s: %s, ip proto:%s, from %s to %s."
								 % (src_ip, dst_ip, path, L4_Proto, L4_src_port, L4_dst_port))
				in_port = self.get_port(src_ip, self.awareness.access_table)
				eth_type = ethernet.ether.ETH_TYPE_IP
				flow_info = (eth_type, src_ip, dst_ip, in_port, L4_Proto, L4_src_port, L4_dst_port)

				self.install_flow(self.datapaths, self.awareness.link_to_port, path, flow_info, None, None)

		# Reroute new mice flows.
		for flow in self.cur_ele_flows:
			if flow not in flows:
				src_ip, dst_ip, L4_Proto, L4_src_port, L4_dst_port = flow
				# Get src and dst switches.
				src_location = self.awareness.get_host_location(src_ip)  # src_location = (dpid, port)
				if src_location:
					src_sw = src_location[0]
				else:
					print "src_sw not found!"
					pass
				dst_location = self.awareness.get_host_location(dst_ip)  # dst_location = (dpid, port)
				if dst_location:
					dst_sw = dst_location[0]
				else:
					print "dst_sw not found!"
					pass

				# print "Reroute mi-flow:", flow
				path = self.get_path(src_sw, dst_sw, L4_Proto, L4_src_port, L4_dst_port,
									 weight=self.WEIGHT_MODEL['hop'])
				self.logger.info("[RR-MI-PATH]%s<-->%s: %s, ip proto:%s, from %s to %s."
								 % (src_ip, dst_ip, path, L4_Proto, L4_src_port, L4_dst_port))
				in_port = self.get_port(src_ip, self.awareness.access_table)
				eth_type = ethernet.ether.ETH_TYPE_IP
				flow_info = (eth_type, src_ip, dst_ip, in_port, L4_Proto, L4_src_port, L4_dst_port)

				self.install_flow(self.datapaths, self.awareness.link_to_port, path, flow_info, None, None)

		self.cur_ele_flows = flows
		# print self.cur_ele_flows

