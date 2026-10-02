"""Send one command to the Constellation KSP bridge (UDP 127.0.0.1:47821) and print the reply.

    python spikes/ksp/kctl.py info
    python spikes/ksp/kctl.py reshape Mun 0.5 0.5
    python spikes/ksp/kctl.py map on
"""

import socket
import sys


def send(command: str, timeout: float = 5.0) -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        s.sendto(command.encode(), ("127.0.0.1", 47821))
        try:
            return s.recvfrom(65535)[0].decode()
        except socket.timeout:
            return '{"error": "no reply - is KSP in the flight scene with the plugin loaded?"}'


if __name__ == "__main__":
    print(send(" ".join(sys.argv[1:]) or "info"))
