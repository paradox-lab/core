"""
控制Node数量，观察性能

sudo python3 nodes.py 10
sudo python3 nodes.py 20

"""
import cProfile, pstats, io
from pstats import SortKey
#
pr = cProfile.Profile(subcalls=False, builtins=False)
pr.enable()

# =========================================================
import logging

logging.basicConfig(level=logging.INFO)

# required imports
import sys
from functools import lru_cache

from core.emulator.coreemu import CoreEmu
from core.emulator.data import IpPrefixes, NodeOptions
from core.emulator.enumerations import EventTypes
from core.nodes.base import CoreNode

# create emulator instance for creating sessions and utility methods
coreemu = CoreEmu()
session = coreemu.create_session()

# must be in configuration state for nodes to start, when using "node_add" below
session.set_state(EventTypes.CONFIGURATION_STATE)


# create nodes
def create_nodes(n):
    if len(sys.argv) > 1:
        n = min(n + 1, int(sys.argv[1]))

    for j in range(n):
        options = NodeOptions(x=(j + 1) * 100, y=100)
        session.add_node(CoreNode, options=options)

    start = 0
    for i in range(1, n+1):
        n1 = session.nodes[i]
        for j in range(i+1, n+1):
            n2 = session.nodes[j]
            ip_prefixes = IpPrefixes(ip4_prefix=f"10.0.{start}.0/24")
            iface1 = ip_prefixes.create_iface(n1)
            iface2 = ip_prefixes.create_iface(n2)
            session.add_link(n1.id, n2.id, iface1, iface2)

        start += 1


create_nodes(50)

# start session
session.instantiate()

pr.disable()
s = io.StringIO()
sortby = SortKey.CUMULATIVE
ps = pstats.Stats(pr, stream=s).sort_stats(sortby)
ps.print_stats(.005)

print()
print()
print(s.getvalue())

# do whatever you like here

print("nodes数量(包括link)", len(session.nodes))
input("press enter to shutdown")

# ================================================================
pr = cProfile.Profile(subcalls=False, builtins=False)
pr.enable()

# stop session
session.shutdown()


pr.disable()
s = io.StringIO()
sortby = SortKey.CUMULATIVE
ps = pstats.Stats(pr, stream=s).sort_stats(sortby)
ps.print_stats(.005)

print()
print()
print(s.getvalue())

# =====================================================


