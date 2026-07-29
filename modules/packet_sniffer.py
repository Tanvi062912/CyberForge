import threading
from datetime import datetime
try:
    from scapy.all import sniff, IP, TCP, UDP, ICMP, ARP
    SCAPY_AVAILABLE = True
except Exception:
    SCAPY_AVAILABLE = False

# Global volatile memory buffers tracking data link matrices
captured_packets = []
is_sniffing = False
sniff_thread = None


def scapy_packet_callback(packet):
    """Callback execution loop fired by Scapy whenever a raw network layer drops."""
    global captured_packets

    # Process only layers passing distinct valid network address tags
    if packet.haslayer(IP) or packet.haslayer(ARP):
        timestamp = datetime.now().strftime("%H:%M:%S")
        length = len(packet)
        
        # ---------------------------------------------
        # INTERRUPT LAYER 3 / LAYER 4 SCHEMES
        # ---------------------------------------------
        if packet.haslayer(IP):
            src_ip = packet[IP].src
            dst_ip = packet[IP].dst
            
            if packet.haslayer(TCP):
                proto = "TCP"
                port = packet[TCP].dport
                info = f"Flags: {packet[TCP].flags} | Port: {packet[TCP].sport} -> {packet[TCP].dport}"
            elif packet.haslayer(UDP):
                proto = "UDP"
                port = packet[UDP].dport
                info = f"User Datagram Protocol | Port: {packet[UDP].sport} -> {packet[UDP].dport}"
            elif packet.haslayer(ICMP):
                proto = "ICMP"
                port = 0
                info = f"ICMP Ping Type: {packet[ICMP].type} Code: {packet[ICMP].code}"
            else:
                proto = "IP"
                port = 0
                info = f"IP Protocol Type ID: {packet[IP].proto}"
                
        elif packet.haslayer(ARP):
            proto = "ARP"
            src_ip = packet[ARP].psrc
            dst_ip = packet[ARP].pdst
            port = 0
            info = f"ARP Request/Reply | Opcode: {packet[ARP].op}"

        # ---------------------------------------------
        # CONVERT PACKET HEADERS TO RAW HEXADECIMAL STACK
        # ---------------------------------------------
        try:
            raw_bytes = bytes(packet)
            hex_dump = " ".join(f"{b:02x}" for b in raw_bytes[:64])
            if len(raw_bytes) > 64:
                hex_dump += " ..."
        except Exception:
            hex_dump = "Hex payload context unreadable."

        # Compile data structural record matching app.py keys perfectly
        packet_data = {
            "time": timestamp,
            "src": src_ip,
            "dst": dst_ip,
            "protocol": proto,
            "port": port,
            "length": length,
            "info": info,
            "hex": hex_dump
        }

        captured_packets.append(packet_data)
        
        # Keep ring storage bounded to avoid running out of RAM
        if len(captured_packets) > 500:
            captured_packets.pop(0)

def background_sniffer():
    """Continuous thread capture driver."""
    global is_sniffing
    while is_sniffing:
        if SCAPY_AVAILABLE:
            try:
                sniff(prn=scapy_packet_callback, count=5, timeout=1)
            except Exception:
                is_sniffing = False
        else:
            is_sniffing = False


# ========================================================
# CORE SYSTEM EXPORT ROUTINES BOUND TO YOUR APP.PY
# ========================================================

def start_capture():
    """Toggles active network listening engines on thread forks."""
    global is_sniffing, sniff_thread
    if not is_sniffing:
        is_sniffing = True
        sniff_thread = threading.Thread(target=background_sniffer, daemon=True)
        sniff_thread.start()

def stop_capture():
    """Signals background packet processing matrices to sleep."""
    global is_sniffing
    is_sniffing = False

def get_packets():
    """Feeds tracked stack variables directly to pipeline API filters."""
    global captured_packets
    return captured_packets

def clear_packets():
    """Wipes memory pool registers cleanly."""
    global captured_packets
    captured_packets.clear()