from core.api.grpc import client
from core.api.grpc.wrappers import ConfigServiceData, Position, Interface

# interface helper
iface_helper = client.InterfaceHelper(ip4_prefix="10.0.0.0/24", ip6_prefix="2001::/64")

# create grpc client and connect
core = client.CoreGrpcClient()
core.connect()

# add session
session = core.create_session()

positions = [(449.0, 83.0),
             (281.0, 180.0),
             (601.0, 183.0),
             (352.0, 372.0),
             (583.0, 374.0),
             (645.0, 28.0),
             (813.0, 185.0),
             (671.0, 504.0),
             (220.0, 503.0),
             (121.0, 158.0)
             ]

for i, p in enumerate(positions, 1):
    position = Position(x=p[0], y=p[1])
    node = session.add_node(i, name=f"n{i}", model="router", position=position)
    node.services.clear()
    node.config_services.add("zebra")
    node.config_services.add("BGP")
    node.config_services.add("IPForward")
    service_config = node.config_service_configs.setdefault("zebra",
                                                            ConfigServiceData())
    with open(f'{node.name}.conf/usr.local.etc.quagga/Quagga.conf') as file:
        service_config.templates['/usr/local/etc/quagga/Quagga.conf'] = file.read()

    service_config.templates['/usr/local/etc/quagga/Quagga.conf'] += "hostname Router\n"
    service_config.templates['/usr/local/etc/quagga/Quagga.conf'] += "password zebra\n"
    service_config.templates[
        '/usr/local/etc/quagga/Quagga.conf'] += "enable password zebra\n"

nodes = session.nodes

links = [
    ((1, 6), (0, 0)),
    ((3, 7), (0, 0)),
    ((5, 8), (0, 0)),
    ((4, 9), (0, 0)),
    ((2, 10), (0, 0)),
    ((1, 4), (1, 1)),
    ((1, 5), (2, 1)),
    ((2, 4), (1, 2)),
    ((2, 5), (2, 2)),
    ((3, 4), (1, 3)),
    ((3, 5), (2, 3)),
    ((4, 5), (4, 4)),
]

for node_id, iface_id in links:
    iface1 = iface_helper.create_iface(node_id[0], iface_id[0])
    iface2 = iface_helper.create_iface(node_id[1], iface_id[1])
    session.add_link(node1=nodes[node_id[0]],
                     node2=nodes[node_id[1]],
                     iface1=iface1,
                     iface2=iface2)

# start session
core.start_session(session)
core.close()
