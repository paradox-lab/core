from typing import List

from core.configservices.frrservices.services import FrrService, ConfigService, CoreInterface, get_router_id


class FRRLdp(FrrService, ConfigService):
    name: str = "FRRLDP"
    shutdown: List[str] = ["killall ldpd"]
    validate: List[str] = ["pidof ldpd"]
    custom_needed: bool = True
    ipv4_routing: bool = True
    ipv6_routing: bool = True
    startup: List[str] = ["/usr/lib/frr/ldpd -d -f /usr/local/etc/frr/frr.conf"]

    def frr_config(self) -> str:
        router_id = get_router_id(self.node)
        text = f"""
        ! LDP configuration
        mpls ldp
          dual-stack transport-connection prefer ipv4
          dual-stack cisco-interop
          router-id {router_id}

          address-family ipv4
           !
           interface eth0
           !
        !
        """
        return self.clean_text(text)

    def frr_iface_config(self, iface: CoreInterface) -> str:
        return ""


