import subprocess

from core.api.grpc import client
from core.api.grpc.wrappers import ConfigServiceData

# interface helper
# iface_helper = client.InterfaceHelper(ip4_prefix="10.0.0.0/24", ip6_prefix="2001::/64")

# create grpc client and connect

# add session
# session = core.create_session(session_id=998)
#
complete = subprocess.run("core-cli xml -f session-deployed.xml", shell=True, capture_output=True)
assert complete.returncode == 0

output = complete.stdout.decode()
print(output)
session_id = output.rstrip().split(",")[-1]

core = client.CoreGrpcClient()
core.connect()
session = core.get_session(int(session_id))

for node in session.nodes.values():
    node.services.clear()
    node.config_services.add("zebra")
    node.config_services.add("BGP")
    node.config_services.add("IPForward")
    service_config = node.config_service_configs.setdefault("zebra", ConfigServiceData())
    with open(f'{node.name}.conf/usr.local.etc.quagga/Quagga.conf') as file:
        service_config.templates['/usr/local/etc/quagga/Quagga.conf'] = file.read()
    service_config.templates['/usr/local/etc/quagga/Quagga.conf'] += "hostname Router\n"
    service_config.templates['/usr/local/etc/quagga/Quagga.conf'] += "password zebra\n"
    service_config.templates['/usr/local/etc/quagga/Quagga.conf'] += "enable password zebra\n"

# start session
core.start_session(session)
core.close()

# =================================================
# 上面的方法不行 ..
# core = client.CoreGrpcClient()
# core.connect()
# session = core.create_session(session_id=998)
# session.op
