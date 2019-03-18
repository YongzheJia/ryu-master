from ryu.base import app_manager
from ryu.ofproto import ofproto_v1_3, ofproto_v1_3_parser
from ryu.controller.handler import MAIN_DISPATCHER, CONFIG_DISPATCHER, set_ev_cls
from ryu.controller import ofp_event
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet


class ExampleSwitch(app_manager.RyuApp):
    """example"""

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(ExampleSwitch, self).__init__(*args, **kwargs)
        self.mac_to_port = {}

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        ofp_parser = datapath.ofproto_parser

        # install the table-miss entry
        match = ofp_parser.OFPMatch()
        actions = [ofp_parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                              ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

    def add_flow(self, datapath, priority, match, actions):
        ofproto = datapath.ofproto
        ofp_parser = datapath.ofproto_parser

        # contruct a flow_mod msg and send it
        inst = [ofp_parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                                 actions)]
        mod = ofp_parser.OFPFlowMod(datapath=datapath, priority=priority,
                                    match=match, instructions=inst)
        datapath.send_msg(mod)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        ofp_parser = datapath.ofproto_parser

        # get datapath id to identify switch
        dpid = datapath.id
        self.mac_to_port.setdefault(dpid, {})

        # save the info
        # parser and analylize the received packet
        pkt = packet.Packet(msg.data)
        eth_pkt = pkt.get_protocol(ethernet.ethernet)
        dst = eth_pkt.dst
        src = eth_pkt.src
        in_port = msg.match['in_port']

        self.logger.info("packet in %s %s %s %s", dpid, src, dst, in_port)


        # learn a src_mac address to avoid FLOOD next time
        self.mac_to_port[dpid][src] = in_port

        # if the dst_mac has already learned,
        # decide which port to send the pkt, otherwise flood.
        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
        else:
            out_port = ofproto.OFPP_FLOOD

        # construct actions
        actions = [ofp_parser.OFPActionOutput(out_port)]

        # install a flow mod msg
        if out_port != ofproto.OFPP_FLOOD:
            match = ofp_parser.OFPMatch(in_port=in_port, eth_dst=dst)
            self.add_flow(datapath, 1, match, actions)

        # send packet_out
        out = ofp_parser.OFPPacketOut(
            datapath=datapath, buffer_id=msg.buffer_id,  in_port=in_port,
            actions=actions)
        datapath.send_msg(out)




