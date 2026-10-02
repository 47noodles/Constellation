"""Send one command to the NMS test mod's UDP channel and print the reply.

    python spikes/nms/ctl.py status
    python spikes/nms/ctl.py hold 3 2
    python spikes/nms/ctl.py ship cruise
"""

import socket
import sys

HOST, PORT = "127.0.0.1", 47801


def send(command: str, timeout: float = 5.0) -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        s.sendto(command.encode(), (HOST, PORT))
        try:
            data, _ = s.recvfrom(65536)
        except socket.timeout:
            return '{"error": "no reply - is NMS running with the mod loaded and not stuck loading?"}'
        return data.decode()


if __name__ == "__main__":
    print(send(" ".join(sys.argv[1:]) or "status"))
