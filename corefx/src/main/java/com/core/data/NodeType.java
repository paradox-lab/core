package com.core.data;

import lombok.Data;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;

import java.util.Collection;
import java.util.HashMap;
import java.util.Map;

@Data
public class NodeType {
    private static final Logger logger = LogManager.getLogger();
    public static final int DEFAULT = 0;
    public static final int SWITCH = 4;
    public static final int HUB = 5;
    public static final int WLAN = 6;
    public static final int EMANE = 10;
    private static final Map<String, NodeType> LOOKUP = new HashMap<>();
    private static final Map<Integer, String> DISPLAY_MAP = new HashMap<>();
    private final int value;
    private String display;
    private String model;
    private String icon;

    //    PHYSICAL = 1
//    RJ45 = 7
//    TUNNEL = 8
//    KTUNNEL = 9
//    EMANE = 10
//    TAP_BRIDGE = 11
//    PEER_TO_PEER = 12
//    CONTROL_NET = 13
//    EMANE_NET = 14;

    static {
        addNodeType(new NodeType(DEFAULT, "host", "Host", "/icons/host-100.png"));
        addNodeType(new NodeType(DEFAULT, "PC", "PC", "/icons/pc-100.png"));
        addNodeType(new NodeType(DEFAULT, "mdr", "MDR", "/icons/router-100.png"));
        addNodeType(new NodeType(SWITCH, "Switch", "/icons/switch-100.png"));
        addNodeType(new NodeType(HUB, "Hub", "/icons/hub-100.png"));
        addNodeType(new NodeType(WLAN, "wlan", "WLAN", "/icons/wlan-100.png"));
        addNodeType(new NodeType(EMANE, "EMANE", "/icons/emane-100.png"));

        DISPLAY_MAP.put(HUB, "Hub");
        DISPLAY_MAP.put(SWITCH, "Switch");
        DISPLAY_MAP.put(WLAN, "WLAN");
        DISPLAY_MAP.put(EMANE, "EMANE");
    }

    public NodeType(int value, String display, String icon) {
        this(value, null, display, icon);
    }


    public NodeType(int value, String model, String display, String icon) {
        this.value = value;
        this.model = model;
        this.display = display;
        this.icon = icon;
    }

    public String getKey() {
        if (model == null) {
            return Integer.toString(value);
        } else {
            return String.format("%s-%s", value, model);
        }
    }

    public static NodeType getNodeType(String key) {
        return LOOKUP.get(key);
    }

    public static String getDisplay(Integer value) {
        return DISPLAY_MAP.get(value);
    }

    public static void addNodeType(NodeType nodeType) {
        LOOKUP.put(nodeType.getKey(), nodeType);
    }

    public static Collection<NodeType> getNodeTypes() {
        return LOOKUP.values();
    }
}
