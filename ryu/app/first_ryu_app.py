from ryu.base import app_manager
from ryu.ofproto import ofproto_v1_3_parser


class L2Switch(app_manager.RyuApp):
    def __init__(self, *args, **kwargs):
        super(L2Switch, self).__init__(*args, **kwargs)


match = ofproto_v1_3_parser.OFPMatch(in_port=1, eth_type=0x0800, ipv4_src='10.0.0.1', eth_dst='10:10:10:10:10:10')

if 'in_port' in match:
    print match


print type(match)