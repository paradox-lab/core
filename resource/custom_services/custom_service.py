from typing import Dict, List

from core.config import ConfigString, ConfigBool, Configuration
from core.configservice.base import ConfigService, ConfigServiceMode, ShadowDir
from core.configservices.quaggaservices.services import Bgp, get_router_id
from core.nodes.interface import CoreInterface

# class that subclasses ConfigService
class ExampleService(ConfigService):
    # unique name for your service within CORE
    name: str = "Example"
    # the group your service is associated with, used for display in GUI
    group: str = "ExampleGroup"
    # directories that the service should shadow mount, hiding the system directory
    directories: List[str] = [
       "/usr/local/core",
    ]
    # files that this service should generate, defaults to nodes home directory
    # or can provide an absolute path to a mounted directory
    files: List[str] = [
        "example-start.sh",
        "/usr/local/core/file1",
    ]
    # executables that should exist on path, that this service depends on
    executables: List[str] = []
    # other services that this service depends on, can be used to define service start order
    dependencies: List[str] = []
    # commands to run to start this service
    startup: List[str] = []
    # commands to run to validate this service
    validate: List[str] = []
    # commands to run to stop this service
    shutdown: List[str] = []
    # validation mode, blocking, non-blocking, and timer
    validation_mode: ConfigServiceMode = ConfigServiceMode.BLOCKING
    # configurable values that this service can use, for file generation
    default_configs: List[Configuration] = [
        ConfigString(id="value1", label="Text"),
        ConfigBool(id="value2", label="Boolean"),
        ConfigString(id="value3", label="Multiple Choice", options=["value1", "value2", "value3"]),
    ]
    # sets of values to set for the configuration defined above, can be used to
    # provide convenient sets of values to typically use
    modes: Dict[str, Dict[str, str]] = {
        "mode1": {"value1": "value1", "value2": "0", "value3": "value2"},
        "mode2": {"value1": "value2", "value2": "1", "value3": "value3"},
        "mode3": {"value1": "value3", "value2": "0", "value3": "value1"},
    }
    # defines directories that this service can help shadow within a node
    shadow_directories: List[ShadowDir] = [
        ShadowDir(path="/user/local/core", src="/opt/core")
    ]

    def get_text_template(self, name: str) -> str:
        return """
        # sample script 1
        # node id(${node.id}) name(${node.name})
        # config: ${config}
        echo hello
        """


class RR(Bgp):
    name = "BgpRR"

    def quagga_config(self) -> str:
        router_id = get_router_id(self.node)
        text = f"""
        ! BGP configuration
        ! You should configure the AS number below
        ! along with this router's peers.
        router bgp {self.node.id}
          bgp router-id {router_id}
          redistribute connected
          !neighbor 1.2.3.4 remote-as 555
        !
        """
        return self.clean_text(text)

    def quagga_iface_config(self, iface: CoreInterface) -> str:
        return ""
