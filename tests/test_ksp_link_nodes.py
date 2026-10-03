import json
import socket
import threading
import unittest
from dataclasses import dataclass

from constellation.ksp_link import KSP_ADDR, KspLink, add_node_cmd


@dataclass(frozen=True)
class Node:
    ut: float
    prograde: float
    normal: float
    radial: float


class FakeKsp(threading.Thread):
    """A UDP peer on KSP's port that speaks the plugin's maneuver-node commands."""

    def __init__(self):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(KSP_ADDR)
        self.sock.settimeout(0.2)
        self.received = []
        self.nodes = []
        self._halt = False

    def run(self):
        while not self._halt:
            try:
                data, addr = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            line = data.decode()
            self.received.append(line)
            self.sock.sendto(json.dumps(self.reply(line)).encode(), addr)

    def reply(self, line):
        w = line.split()
        cmd = w[0] if w else "info"
        if cmd == "addnode":
            node = {"index": len(self.nodes), "ut": float(w[1]), "prograde": float(w[2]),
                    "normal": float(w[3]), "radial": float(w[4])}
            self.nodes.append(node)
            return {"ok": True, "node": node}
        if cmd == "clearnodes":
            self.nodes = []
            return {"ok": True, "nodes": []}
        if cmd == "readnodes":
            return {"ok": True, "nodes": list(self.nodes)}
        if cmd == "info":
            return {"ut": 0.0, "bodies": []}
        if cmd == "burn":
            return {"ok": True, "ut": 0.0, "vessel": {}}
        return {"error": "unknown command " + cmd}

    def stop(self):
        self._halt = True
        self.join(timeout=1.0)
        self.sock.close()


class NodeCommandTests(unittest.TestCase):
    def setUp(self):
        self.peer = FakeKsp()
        self.peer.start()
        self.link = KspLink()

    def tearDown(self):
        self.peer.stop()
        self.link.sock.close()

    def test_add_node_cmd_wire_format(self):
        cmd = add_node_cmd(Node(ut=1234.5, prograde=-10.0, normal=2.5, radial=0.0))
        self.assertEqual(cmd, "addnode 1234.5 -10.0 2.5 0.0")

    def test_add_node_encodes_and_decodes(self):
        node = Node(ut=600.0, prograde=850.25, normal=-3.5, radial=1.0)
        got = self.link.add_node(node)
        self.assertEqual(self.peer.received[-1], add_node_cmd(node))
        self.assertEqual(got, {"index": 0, "ut": 600.0, "prograde": 850.25, "normal": -3.5, "radial": 1.0})

    def test_read_nodes_inner_to_outer(self):
        self.link.add_node(Node(ut=100.0, prograde=1.0, normal=0.0, radial=0.0))
        self.link.add_node(Node(ut=200.0, prograde=2.0, normal=0.0, radial=0.0))
        nodes = self.link.read_nodes()
        self.assertEqual([n["ut"] for n in nodes], [100.0, 200.0])
        self.assertEqual([n["index"] for n in nodes], [0, 1])

    def test_clear_nodes_empties(self):
        self.link.add_node(Node(ut=100.0, prograde=1.0, normal=0.0, radial=0.0))
        self.assertEqual(self.link.clear_nodes(), {"ok": True, "nodes": []})
        self.assertEqual(self.link.read_nodes(), [])

    def test_execute_node_issues_existing_burn(self):
        node = Node(ut=0.0, prograde=12.5, normal=-1.0, radial=0.25)
        result = self.link.execute_node(node)
        self.assertEqual(self.peer.received[-1], "burn 12.5 -1.0 0.25")
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
