import logging
import os
import tempfile
import time
from Queue import Queue, Empty
from itertools import repeat

import grpc
from concurrent import futures

import core_pb2
import core_pb2_grpc
from core.conf import ConfigShim
from core.data import ConfigData, FileData
from core.emulator.emudata import NodeOptions, InterfaceData, LinkOptions
from core.enumerations import NodeTypes, EventTypes, LinkTypes, MessageFlags, ConfigFlags, ConfigDataTypes
from core.misc import nodeutils
from core.mobility import BasicRangeModel, Ns2ScriptedMobility
from core.service import ServiceManager, ServiceShim

_ONE_DAY_IN_SECONDS = 60 * 60 * 24


def convert_value(value):
    if value is None:
        return value
    else:
        return str(value)


def update_proto(obj, **kwargs):
    for key in kwargs:
        value = kwargs[key]
        if value is not None:
            setattr(obj, key, value)


def get_config_groups(config, configurable_options):
    groups = []
    config_options = []

    for configuration in configurable_options.configurations():
        value = config[configuration.id]
        config_option = core_pb2.ConfigOption()
        config_option.label = configuration.label
        config_option.name = configuration.id
        config_option.value = value
        config_option.type = configuration.type.value
        config_option.select.extend(configuration.options)
        config_options.append(config_option)

    for config_group in configurable_options.config_groups():
        start = config_group.start - 1
        stop = config_group.stop
        config_group_proto = core_pb2.ConfigGroup()
        config_group_proto.name = config_group.name
        config_group_proto.options.extend(config_options[start: stop])
        groups.append(config_group_proto)

    return groups


def convert_link(session, link_data, link):
    if link_data.interface1_id is not None:
        node = session.get_object(link_data.node1_id)
        interface = node.netif(link_data.interface1_id)
        link.interface_one.id = link_data.interface1_id
        link.interface_one.name = interface.name
        update_proto(
            link.interface_one,
            mac=convert_value(link_data.interface1_mac),
            ip4=convert_value(link_data.interface1_ip4),
            ip4mask=link_data.interface1_ip4_mask,
            ip6=convert_value(link_data.interface1_ip6),
            ip6mask=link_data.interface1_ip6_mask
        )

    if link_data.interface2_id is not None:
        node = session.get_object(link_data.node2_id)
        interface = node.netif(link_data.interface2_id)
        link.interface_two.id = link_data.interface2_id
        link.interface_two.name = interface.name
        update_proto(
            link.interface_two,
            mac=convert_value(link_data.interface2_mac),
            ip4=convert_value(link_data.interface2_ip4),
            ip4mask=link_data.interface2_ip4_mask,
            ip6=convert_value(link_data.interface2_ip6),
            ip6mask=link_data.interface2_ip6_mask
        )

    link.node_one = link_data.node1_id
    link.node_two = link_data.node2_id
    link.type = link_data.link_type
    update_proto(
        link.options,
        opaque=link_data.opaque,
        jitter=link_data.jitter,
        key=link_data.key,
        mburst=link_data.mburst,
        mer=link_data.mer,
        per=link_data.per,
        bandwidth=link_data.bandwidth,
        burst=link_data.burst,
        delay=link_data.delay,
        dup=link_data.dup,
        unidirectional=link_data.unidirectional
    )


def send_objects(session):
    time.sleep(1)
    # find all nodes and links
    nodes_data = []
    links_data = []
    with session._objects_lock:
        for obj in session.objects.itervalues():
            node_data = obj.data(message_type=MessageFlags.ADD.value)
            if node_data:
                nodes_data.append(node_data)

            node_links = obj.all_link_data(flags=MessageFlags.ADD.value)
            for link_data in node_links:
                links_data.append(link_data)

    # send all nodes first, so that they will exist for any links
    for node_data in nodes_data:
        session.broadcast_node(node_data)

    for link_data in links_data:
        session.broadcast_link(link_data)

    # send mobility model info
    for node_id in session.mobility.nodes():
        for model_name, config in session.mobility.get_all_configs(node_id).iteritems():
            model_class = session.mobility.models[model_name]
            logging.debug("mobility config: node(%s) class(%s) values(%s)", node_id, model_class, config)
            config_data = ConfigShim.config_data(0, node_id, ConfigFlags.UPDATE.value, model_class, config)
            session.broadcast_config(config_data)

    # send emane model info
    for node_id in session.emane.nodes():
        for model_name, config in session.emane.get_all_configs(node_id).iteritems():
            model_class = session.emane.models[model_name]
            logging.debug("emane config: node(%s) class(%s) values(%s)", node_id, model_class, config)
            config_data = ConfigShim.config_data(0, node_id, ConfigFlags.UPDATE.value, model_class, config)
            session.broadcast_config(config_data)

    # service customizations
    service_configs = session.services.all_configs()
    for node_id, service in service_configs:
        opaque = "service:%s" % service.name
        data_types = tuple(repeat(ConfigDataTypes.STRING.value, len(ServiceShim.keys)))
        node = session.get_object(node_id)
        values = ServiceShim.tovaluelist(node, service)
        config_data = ConfigData(
            message_type=0,
            node=node_id,
            object=session.services.name,
            type=ConfigFlags.UPDATE.value,
            data_types=data_types,
            data_values=values,
            session=str(session.session_id),
            opaque=opaque
        )
        session.broadcast_config(config_data)

        for file_name, config_data in session.services.all_files(service):
            file_data = FileData(
                message_type=MessageFlags.ADD.value,
                node=node_id,
                name=str(file_name),
                type=opaque,
                data=str(config_data)
            )
            session.broadcast_file(file_data)

    # TODO: send location info

    # send hook scripts
    for state in sorted(session._hooks.keys()):
        for file_name, config_data in session._hooks[state]:
            file_data = FileData(
                message_type=MessageFlags.ADD.value,
                name=str(file_name),
                type="hook:%s" % state,
                data=str(config_data)
            )
            session.broadcast_file(file_data)

    # send session configuration
    session_config = session.options.get_configs()
    config_data = ConfigShim.config_data(0, None, ConfigFlags.UPDATE.value, session.options, session_config)
    session.broadcast_config(config_data)

    # send session metadata
    data_values = "|".join(["%s=%s" % item for item in session.metadata.get_configs().iteritems()])
    data_types = tuple(ConfigDataTypes.STRING.value for _ in session.metadata.get_configs())
    config_data = ConfigData(
        message_type=0,
        object=session.metadata.name,
        type=ConfigFlags.NONE.value,
        data_types=data_types,
        data_values=data_values
    )
    session.broadcast_config(config_data)

    logging.info("informed GUI about %d nodes and %d links", len(nodes_data), len(links_data))


class CoreApiServer(core_pb2_grpc.CoreApiServicer):
    def __init__(self, coreemu):
        super(CoreApiServer, self).__init__()
        self.coreemu = coreemu

    def get_session(self, _id, context):
        session = self.coreemu.sessions.get(_id)
        if not session:
            context.abort(grpc.StatusCode.NOT_FOUND, "session not found")
        return session

    def get_node(self, session, _id, context):
        node = session.get_object(_id)
        if not node:
            context.abort(grpc.StatusCode.NOT_FOUND, "node not found")
        return node

    def CreateSession(self, request, context):
        session = self.coreemu.create_session()
        session.set_state(EventTypes.DEFINITION_STATE)

        # default set session location
        session.location.setrefgeo(47.57917, -122.13232, 2.0)
        session.location.refscale = 150000.0

        response = core_pb2.CreateSessionResponse()
        response.id = session.session_id
        response.state = session.state
        return response

    def DeleteSession(self, request, context):
        response = core_pb2.DeleteSessionResponse()
        response.result = self.coreemu.delete_session(request.id)
        return response

    def GetSessions(self, request, context):
        response = core_pb2.GetSessionsResponse()
        for session_id in self.coreemu.sessions:
            session = self.coreemu.sessions[session_id]
            session_data = response.sessions.add()
            session_data.id = session_id
            session_data.state = session.state
            session_data.nodes = session.get_node_count()
        return response

    def GetSessionLocation(self, request, context):
        session = self.get_session(request.id, context)
        x, y, z = session.location.refxyz
        lat, lon, alt = session.location.refgeo
        response = core_pb2.GetSessionLocationResponse()
        update_proto(
            response.position,
            x=x,
            y=y,
            z=z,
            lat=lat,
            lon=lon,
            alt=alt
        )
        update_proto(response, scale=session.location.refscale)
        return response

    def SetSessionLocation(self, request, context):
        session = self.get_session(request.id, context)

        session.location.refxyz = (request.position.x, request.position.y, request.position.z)
        session.location.setrefgeo(request.position.lat, request.position.lon, request.position.alt)
        session.location.refscale = request.scale

        response = core_pb2.SetSessionLocationResponse()
        response.result = True
        return response

    def SetSessionState(self, request, context):
        response = core_pb2.SetSessionStateResponse()
        session = self.get_session(request.id, context)

        try:
            state = EventTypes(request.state)
            session.set_state(state)

            if state == EventTypes.INSTANTIATION_STATE:
                # create session directory if it does not exist
                if not os.path.exists(session.session_dir):
                    os.mkdir(session.session_dir)
                session.instantiate()
            elif state == EventTypes.SHUTDOWN_STATE:
                session.shutdown()
            elif state == EventTypes.DATACOLLECT_STATE:
                session.data_collect()
            elif state == EventTypes.DEFINITION_STATE:
                session.clear()

            response.result = True
        except KeyError:
            response.result = False

        return response

    def GetSessionOptions(self, request, context):
        session = self.get_session(request.id, context)

        config = session.options.get_configs()
        defaults = session.options.default_values()
        defaults.update(config)

        groups = get_config_groups(defaults, session.options)

        response = core_pb2.GetSessionOptionsResponse()
        response.groups.extend(groups)
        return response

    def SetSessionOptions(self, request, context):
        session = self.get_session(request.id, context)
        session.options.set_configs(request.config)
        response = core_pb2.SetSessionOptionsResponse()
        response.result = True
        return response

    def GetSession(self, request, context):
        session = self.get_session(request.id, context)
        response = core_pb2.GetSessionResponse()
        response.state = session.state

        for node_id in session.objects:
            node = session.objects[node_id]

            if not isinstance(node.objid, int):
                continue

            node_proto = response.nodes.add()
            node_proto.id = node.objid
            node_proto.name = node.name
            node_proto.type = nodeutils.get_node_type(node.__class__).value
            model = getattr(node, "type", None)
            if model is not None:
                node_proto.model = model

            update_proto(
                node_proto.position,
                x=node.position.x,
                y=node.position.y,
                z=node.position.z
            )

            services = getattr(node, "services", [])
            if services is None:
                services = []
            services = [x.name for x in services]
            node_proto.services.extend(services)

            emane_model = None
            if nodeutils.is_node(node, NodeTypes.EMANE):
                emane_model = node.model.name
            if emane_model is not None:
                node_proto.emane = emane_model

            links_data = node.all_link_data(0)
            for link_data in links_data:
                link = response.links.add()
                convert_link(session, link_data, link)

        return response

    def NodeEvents(self, request, context):
        session = self.get_session(request.id, context)
        queue = Queue()
        session.node_handlers.append(lambda x: queue.put(x))

        while context.is_active():
            try:
                node = queue.get(timeout=1)
                node_event = core_pb2.NodeEvent()
                update_proto(
                    node_event.node,
                    id=node.id,
                    name=node.name,
                    model=node.model
                )
                update_proto(
                    node_event.node.position,
                    x=node.x_position,
                    y=node.y_position
                )
                services = node.services or ""
                node_event.node.services.extend(services.split("|"))
                yield node_event
            except Empty:
                continue

    def LinkEvents(self, request, context):
        session = self.get_session(request.id, context)
        queue = Queue()
        session.link_handlers.append(lambda x: queue.put(x))

        while context.is_active():
            try:
                event = queue.get(timeout=1)
                link_event = core_pb2.LinkEvent()
                if event.interface1_id is not None:
                    interface_one = link_event.link.interface_one
                    update_proto(
                        interface_one,
                        id=event.interface1_id,
                        name=event.interface1_name,
                        mac=convert_value(event.interface1_mac),
                        ip4=convert_value(event.interface1_ip4),
                        ip4mask=event.interface1_ip4_mask,
                        ip6=convert_value(event.interface1_ip6),
                        ip6mask=event.interface1_ip6_mask,
                    )

                if event.interface2_id is not None:
                    interface_two = link_event.link.interface_two
                    update_proto(
                        interface_two,
                        id=event.interface2_id,
                        name=event.interface2_name,
                        mac=convert_value(event.interface2_mac),
                        ip4=convert_value(event.interface2_ip4),
                        ip4mask=event.interface2_ip4_mask,
                        ip6=convert_value(event.interface2_ip6),
                        ip6mask=event.interface2_ip6_mask,
                    )

                link_event.message_type = event.message_type
                update_proto(
                    link_event.link,
                    type=event.link_type,
                    node_one=event.node1_id,
                    node_two=event.node2_id
                )
                update_proto(
                    link_event.link.options,
                    opaque=event.opaque,
                    jitter=event.jitter,
                    key=event.key,
                    mburst=event.mburst,
                    mer=event.mer,
                    per=event.per,
                    bandwidth=event.bandwidth,
                    burst=event.burst,
                    delay=event.delay,
                    dup=event.dup,
                    unidirectional=event.unidirectional
                )
                yield link_event
            except Empty:
                continue

    def SessionEvents(self, request, context):
        session = self.get_session(request.id, context)
        queue = Queue()
        session.event_handlers.append(lambda x: queue.put(x))

        while context.is_active():
            try:
                event = queue.get(timeout=1)
                session_event = core_pb2.SessionEvent()
                event_time = event.time
                if event_time is not None:
                    event_time = float(event_time)
                update_proto(
                    session_event,
                    node=event.node,
                    event=event.event_type,
                    name=event.name,
                    data=event.data,
                    time=event_time,
                    session=session.session_id
                )
                yield session_event
            except Empty:
                continue

    def ConfigEvents(self, request, context):
        session = self.get_session(request.id, context)
        queue = Queue()
        session.config_handlers.append(lambda x: queue.put(x))

        while context.is_active():
            try:
                event = queue.get(timeout=1)
                config_event = core_pb2.ConfigEvent()
                update_proto(
                    config_event,
                    message_type=event.message_type,
                    node=event.node,
                    object=event.object,
                    type=event.type,
                    captions=event.captions,
                    bitmap=event.bitmap,
                    data_values=event.data_values,
                    possible_values=event.possible_values,
                    groups=event.groups,
                    session=event.session,
                    interface=event.interface_number,
                    network_id=event.network_id,
                    opaque=event.opaque
                )
                config_event.data_types.extend(event.data_types)
                yield config_event
            except Empty:
                continue

    def ExceptionEvents(self, request, context):
        session = self.get_session(request.id, context)
        queue = Queue()
        session.exception_handlers.append(lambda x: queue.put(x))

        while context.is_active():
            try:
                event = queue.get(timeout=1)
                exception_event = core_pb2.ExceptionEvent()
                event_time = event.date
                if event_time is not None:
                    event_time = float(event_time)
                update_proto(
                    exception_event,
                    node=event.node,
                    session=event.session,
                    level=event.level,
                    source=event.source,
                    date=event_time,
                    text=event.text,
                    opaque=event.opaque
                )
                yield exception_event
            except Empty:
                continue

    def FileEvents(self, request, context):
        session = self.get_session(request.id, context)
        queue = Queue()
        session.file_handlers.append(lambda x: queue.put(x))

        while context.is_active():
            try:
                event = queue.get(timeout=1)
                file_event = core_pb2.FileEvent()
                update_proto(
                    file_event,
                    message_type=event.message_type,
                    node=event.node,
                    name=event.name,
                    mode=event.mode,
                    number=event.number,
                    type=event.type,
                    source=event.source,
                    session=event.session,
                    data=event.data,
                    compressed_data=event.compressed_data
                )
                yield file_event
            except Empty:
                continue

    def CreateNode(self, request, context):
        session = self.get_session(request.session, context)

        node_id = request.id
        node_type = request.type
        if node_type is None:
            node_type = NodeTypes.DEFAULT.value
        node_type = NodeTypes(node_type)
        logging.info("creating node: %s - %s", node_type.name, request)

        node_options = NodeOptions(name=request.name, model=request.model)
        node_options.icon = request.icon
        node_options.opaque = request.opaque
        node_options.services = request.services

        position = request.position
        node_options.set_position(position.x, position.y)
        node_options.set_location(position.lat, position.lon, position.alt)
        node = session.add_node(_type=node_type, _id=node_id, node_options=node_options)

        # configure emane if provided
        emane_model = request.emane
        if emane_model:
            session.emane.set_model_config(node_id, emane_model)

        response = core_pb2.CreateNodeResponse()
        response.id = node.objid
        return response

    def GetNode(self, request, context):
        session = self.get_session(request.session, context)
        node = self.get_node(session, request.id, context)
        response = core_pb2.GetNodeResponse()

        for interface_id, interface in node._netif.iteritems():
            net_id = None
            if interface.net:
                net_id = interface.net.objid

            interface_proto = response.interfaces.add()
            interface_proto.id = interface_id
            interface_proto.netid = net_id
            interface_proto.name = interface.name
            interface_proto.mac = str(interface.hwaddr)
            interface_proto.mtu = interface.mtu
            interface_proto.flowid = interface.flow_id

        emane_model = None
        if nodeutils.is_node(node, NodeTypes.EMANE):
            emane_model = node.model.name

        update_proto(
            response.node,
            name=node.name,
            type=nodeutils.get_node_type(node.__class__).value,
            emane=emane_model,
            model=node.type
        )

        update_proto(
            response.node.position,
            x=node.position.x,
            y=node.position.y,
            z=node.position.z,
        )

        services = [x.name for x in getattr(node, "services", [])]
        response.node.services.extend(services)
        return response

    def EditNode(self, request, context):
        session = self.get_session(request.session, context)

        node_id = request.id
        node_options = NodeOptions()
        x = request.position.x
        y = request.position.y
        node_options.set_position(x, y)
        lat = request.position.lat
        lon = request.position.lon
        alt = request.position.alt
        node_options.set_location(lat, lon, alt)
        logging.debug("updating node(%s) - pos(%s, %s) geo(%s, %s, %s)", node_id, x, y, lat, lon, alt)

        result = session.update_node(node_id, node_options)
        response = core_pb2.EditNodeResponse()
        response.result = result
        return response

    def DeleteNode(self, request, context):
        logging.info("delete node: %s", request)
        session = self.get_session(request.session, context)
        response = core_pb2.DeleteNodeResponse()
        response.result = session.delete_node(request.id)
        return response

    def GetNodeLinks(self, request, context):
        logging.info("get node links: %s", request)
        session = self.get_session(request.session, context)
        node = self.get_node(session, request.id, context)
        response = core_pb2.GetNodeLinksResponse()
        links_data = node.all_link_data(0)
        for link_data in links_data:
            link = response.links.add()
            convert_link(session, link_data, link)

        return response

    def CreateLink(self, request, context):
        session = self.get_session(request.session, context)
        logging.info("adding link: %s", request)
        node_one = request.link.node_one
        node_two = request.link.node_two

        interface_one = None
        interface_one_data = request.link.interface_one
        if interface_one_data:
            name = interface_one_data.name
            if name == "":
                name = None
            mac = interface_one_data.mac
            if mac == "":
                mac = None
            interface_one = InterfaceData(
                _id=interface_one_data.id,
                name=name,
                mac=mac,
                ip4=interface_one_data.ip4,
                ip4_mask=interface_one_data.ip4mask,
                ip6=interface_one_data.ip6,
                ip6_mask=interface_one_data.ip6mask,
            )

        interface_two = None
        interface_two_data = request.link.interface_two
        if interface_two_data:
            name = interface_two_data.name
            if name == "":
                name = None
            mac = interface_two_data.mac
            if mac == "":
                mac = None
            interface_two = InterfaceData(
                _id=interface_two_data.id,
                name=name,
                mac=mac,
                ip4=interface_two_data.ip4,
                ip4_mask=interface_two_data.ip4mask,
                ip6=interface_two_data.ip6,
                ip6_mask=interface_two_data.ip6mask,
            )

        link_type = None
        link_type_value = request.link.type
        if link_type_value is not None:
            link_type = LinkTypes(link_type_value)

        options_data = request.link.options
        link_options = LinkOptions(_type=link_type)
        if options_data:
            link_options.delay = options_data.delay
            link_options.bandwidth = options_data.bandwidth
            link_options.per = options_data.per
            link_options.dup = options_data.dup
            link_options.jitter = options_data.jitter
            link_options.mer = options_data.mer
            link_options.burst = options_data.burst
            link_options.mburst = options_data.mburst
            link_options.unidirectional = options_data.unidirectional
            link_options.key = options_data.key
            link_options.opaque = options_data.opaque

        session.add_link(node_one, node_two, interface_one, interface_two, link_options=link_options)

        response = core_pb2.CreateLinkResponse()
        response.result = True
        return response

    def EditLink(self, request, context):
        logging.info("edit link: %s", request)
        session = self.get_session(request.session, context)

        node_one = request.node_one
        node_two = request.node_two
        interface_one_id = request.interface_one
        interface_two_id = request.interface_two

        options_data = request.options
        link_options = LinkOptions()
        link_options.delay = options_data.delay
        link_options.bandwidth = options_data.bandwidth
        link_options.per = options_data.per
        link_options.dup = options_data.dup
        link_options.jitter = options_data.jitter
        link_options.mer = options_data.mer
        link_options.burst = options_data.burst
        link_options.mburst = options_data.mburst
        link_options.unidirectional = options_data.unidirectional
        link_options.key = options_data.key
        link_options.opaque = options_data.opaque

        session.update_link(node_one, node_two, interface_one_id, interface_two_id, link_options)

        response = core_pb2.EditLinkResponse()
        response.result = True
        return response

    def DeleteLink(self, request, context):
        logging.info("delete link: %s", request)
        session = self.get_session(request.session, context)

        node_one = request.node_one
        node_two = request.node_two
        interface_one = request.interface_one
        interface_two = request.interface_two
        session.delete_link(node_one, node_two, interface_one, interface_two)

        response = core_pb2.DeleteLinkResponse()
        response.result = True
        return response

    def GetHooks(self, request, context):
        session = self.get_session(request.session, context)

        response = core_pb2.GetHooksResponse()
        for state, state_hooks in session._hooks.iteritems():
            for file_name, file_data in state_hooks:
                hook = response.hooks.add()
                hook.state = state
                hook.file = file_name
                hook.data = file_data

        return response

    def AddHook(self, request, context):
        session = self.get_session(request.session, context)

        hook = request.hook
        session.add_hook(hook.state, hook.file, None, hook.data)
        response = core_pb2.AddHookResponse()
        response.result = True
        return response

    def GetMobilityConfigs(self, request, context):
        session = self.get_session(request.session, context)

        response = core_pb2.GetMobilityConfigsResponse()
        for node_id, model_config in session.mobility.node_configurations.iteritems():
            if node_id == -1:
                continue

            for model_name in model_config.iterkeys():
                if model_name != Ns2ScriptedMobility.name:
                    continue

                config = session.mobility.get_model_config(node_id, model_name)
                groups = get_config_groups(config, Ns2ScriptedMobility)
                mobility_config = response.configs[node_id]
                mobility_config.groups.extend(groups)
        return response

    def GetMobilityConfig(self, request, context):
        session = self.get_session(request.session, context)
        config = session.mobility.get_model_config(request.id, Ns2ScriptedMobility.name)
        groups = get_config_groups(config, Ns2ScriptedMobility)
        response = core_pb2.GetMobilityConfigResponse()
        response.groups.extend(groups)
        return response

    def SetMobilityConfig(self, request, context):
        session = self.get_session(request.session, context)
        session.mobility.set_model_config(request.id, Ns2ScriptedMobility.name, request.config)
        response = core_pb2.SetMobilityConfigResponse()
        response.result = True
        return response

    def MobilityAction(self, request, context):
        session = self.get_session(request.session, context)
        node = self.get_node(session, request.id, context)

        response = core_pb2.MobilityActionResponse()
        response.result = True
        if request.action == core_pb2.MOBILITY_START:
            node.mobility.start()
        elif request.action == core_pb2.MOBILITY_PAUSE:
            node.mobility.pause()
        elif request.action == core_pb2.MOBILITY_STOP:
            node.mobility.stop(move_initial=True)
        else:
            response.result = False

        return response

    def GetServices(self, request, context):
        response = core_pb2.GetServicesResponse()
        for service in ServiceManager.services.itervalues():
            service_proto = response.services.add()
            service_proto.group = service.group
            service_proto.name = service.name
        return response

    def GetServiceDefaults(self, request, context):
        session = self.get_session(request.session, context)

        response = core_pb2.GetServiceDefaultsResponse()
        for node_type in session.services.default_services:
            services = session.services.default_services[node_type]
            service_defaults = response.defaults.add()
            service_defaults.node_type = node_type
            service_defaults.services.extend(services)
        return response

    def SetServiceDefaults(self, request, context):
        session = self.get_session(request.session, context)
        session.services.default_services.clear()
        for service_defaults in request.defaults:
            session.services.default_services[service_defaults.node_type] = service_defaults.services

        response = core_pb2.SetServiceDefaultsResponse()
        response.result = True
        return response

    def GetNodeService(self, request, context):
        session = self.get_session(request.session, context)

        service = session.services.get_service(request.id, request.service, default_service=True)
        response = core_pb2.GetNodeServiceResponse()
        response.service.executables.extend(service.executables)
        response.service.dependencies.extend(service.dependencies)
        response.service.dirs.extend(service.dirs)
        response.service.configs.extend(service.configs)
        response.service.startup.extend(service.startup)
        response.service.validate.extend(service.validate)
        response.service.validation_mode = service.validation_mode.value
        response.service.validation_timer = service.validation_timer
        response.service.shutdown.extend(service.shutdown)
        if service.meta:
            response.service.meta = service.meta
        return response

    def GetNodeServiceFile(self, request, context):
        session = self.get_session(request.session, context)
        node = self.get_node(session, request.id, context)

        service = None
        for current_service in node.services:
            if current_service.name == request.service:
                service = current_service
                break

        response = core_pb2.GetNodeServiceFileResponse()
        if not service:
            return response
        file_data = session.services.get_service_file(node, request.service, request.file)
        response.data = file_data.data
        return response

    def SetNodeService(self, request, context):
        session = self.get_session(request.session, context)

        # guarantee custom service exists
        session.services.set_service(request.id, request.service)
        service = session.services.get_service(request.id, request.service)
        service.startup = tuple(request.startup)
        logging.info("custom startup: %s", service.startup)
        service.validate = tuple(request.validate)
        logging.info("custom validate: %s", service.validate)
        service.shutdown = tuple(request.shutdown)
        logging.info("custom shutdown: %s", service.shutdown)

        response = core_pb2.SetNodeServiceResponse()
        response.result = True
        return response

    def SetNodeServiceFile(self, request, context):
        session = self.get_session(request.session, context)
        session.services.set_service_file(request.id, request.service, request.file, request.data)
        response = core_pb2.SetNodeServiceFileResponse()
        response.result = True
        return response

    def ServiceAction(self, request, context):
        session = self.get_session(request.session, context)
        node = self.get_node(session, request.id, context)

        service = None
        for current_service in node.services:
            if current_service.name == request.service:
                service = current_service
                break

        response = core_pb2.ServiceActionResponse()
        response.result = False

        if not service:
            return response

        status = -1
        if request.action == core_pb2.START:
            status = session.services.startup_service(node, service, wait=True)
        elif request.action == core_pb2.STOP:
            status = session.services.stop_service(node, service)
        elif request.action == core_pb2.RESTART:
            status = session.services.stop_service(node, service)
            if not status:
                status = session.services.startup_service(node, service, wait=True)
        elif request.action == core_pb2.VALIDATE:
            status = session.services.validate_service(node, service)

        if not status:
            response.result = True

        return response

    def GetWlanConfig(self, request, context):
        session = self.get_session(request.session, context)
        config = session.mobility.get_model_config(request.id, BasicRangeModel.name)
        groups = get_config_groups(config, BasicRangeModel)
        response = core_pb2.GetWlanConfigResponse()
        response.groups.extend(groups)
        return response

    def SetWlanConfig(self, request, context):
        session = self.get_session(request.session, context)
        session.mobility.set_model_config(request.id, BasicRangeModel.name, request.config)
        response = core_pb2.SetWlanConfigResponse()
        response.result = True
        return response

    def GetEmaneConfig(self, request, context):
        session = self.get_session(request.session, context)
        config = session.emane.get_configs()
        groups = get_config_groups(config, session.emane.emane_config)
        response = core_pb2.GetEmaneConfigResponse()
        response.groups.extend(groups)
        return response

    def SetEmaneConfig(self, request, context):
        session = self.get_session(request.session, context)
        session.emane.set_configs(request.config)
        response = core_pb2.SetEmaneConfigResponse()
        response.result = True
        return response

    def GetEmaneModels(self, request, context):
        session = self.get_session(request.session, context)

        models = []
        for model in session.emane.models.keys():
            if len(model.split("_")) != 2:
                continue
            models.append(model)

        response = core_pb2.GetEmaneModelsResponse()
        response.models.extend(models)
        return response

    def GetEmaneModelConfig(self, request, context):
        session = self.get_session(request.session, context)
        model = session.emane.models[request.model]
        config = session.emane.get_model_config(request.id, request.model)
        groups = get_config_groups(config, model)
        response = core_pb2.GetEmaneModelConfigResponse()
        response.groups.extend(groups)
        return response

    def SetEmaneModelConfig(self, request, context):
        session = self.get_session(request.session, context)
        session.emane.set_model_config(request.id, request.model, request.config)
        response = core_pb2.SetEmaneModelConfigResponse()
        response.result = True
        return response

    def GetEmaneModelConfigs(self, request, context):
        session = self.get_session(request.session, context)

        response = core_pb2.GetEmaneModelConfigsResponse()
        for node_id, model_config in session.emane.node_configurations.iteritems():
            if node_id == -1:
                continue

            for model_name in model_config.iterkeys():
                model = session.emane.models[model_name]
                config = session.emane.get_model_config(node_id, model_name)
                config_groups = get_config_groups(config, model)
                node_configurations = response.configs[node_id]
                node_configurations.model = model_name
                node_configurations.groups.extend(config_groups)
        return response

    def SaveXml(self, request, context):
        session = self.get_session(request.session, context)

        _, temp_path = tempfile.mkstemp()
        session.save_xml(temp_path)

        with open(temp_path, "rb") as xml_file:
            data = xml_file.read()

        response = core_pb2.SaveXmlResponse()
        response.data = data
        return response

    def OpenXml(self, request, context):
        session = self.coreemu.create_session()
        session.set_state(EventTypes.CONFIGURATION_STATE)

        _, temp_path = tempfile.mkstemp()
        with open(temp_path, "wb") as xml_file:
            xml_file.write(request.data)

        response = core_pb2.OpenXmlResponse()
        try:
            session.open_xml(temp_path, start=True)
            response.session = session.session_id
            response.result = True
        except:
            response.result = False
            logging.exception("error opening session file")
            self.coreemu.delete_session(session.session_id)

        return response


def listen(coreemu, address="[::]:50051"):
    logging.info("starting grpc api: %s", address)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    core_pb2_grpc.add_CoreApiServicer_to_server(CoreApiServer(coreemu), server)
    server.add_insecure_port(address)
    server.start()

    try:
        while True:
            time.sleep(_ONE_DAY_IN_SECONDS)
    except KeyboardInterrupt:
        server.stop(0)
