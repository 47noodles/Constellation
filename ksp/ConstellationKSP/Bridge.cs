// Constellation KSP bridge (KSP 1.12.5): the hidden KSP's side of the coordinator link.
//
// AutoLoad: if GameData/Constellation/autoload.txt exists, its first line names a save
// folder; the main menu loads saves/<folder>/persistent.sfs and starts it. Without the
// file KSP behaves normally, so this never hijacks ordinary play.
//
// Bridge (flight scene): one JSON reply per UDP command on 127.0.0.1:47821.
//   info                                  UT, warp, active vessel orbit, bodies
//   reshape <body> <radiusScale> <gmScale> rescale a body; recompute SOI; re-init orbits around it
//   bodyorbit <body> <smaScale>           rewrite a body's orbit semi-major axis
//   map on|off                            KSP's real map view
//   warp <index>                          TimeWarp.SetRate
//   dismiss                               close PopupDialogs
//   ui find|hide <substring>              list or hide active UI objects (e.g. the 1.12 "What's new" window)
//   shot <file.png>                       screenshot (works without focus)
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using UnityEngine;

namespace Constellation
{
    [KSPAddon(KSPAddon.Startup.MainMenu, true)]
    public class AutoLoad : MonoBehaviour
    {
        private int frames;

        private void Start()
        {
            Application.runInBackground = true;
            GameSettings.SIMULATE_IN_BACKGROUND = true;
        }

        private void Update()
        {
            if (++frames != 30) return; // let the main menu finish building
            string flag = Path.Combine(KSPUtil.ApplicationRootPath, "GameData/Constellation/autoload.txt");
            if (!File.Exists(flag)) return;
            string folder = File.ReadAllLines(flag)[0].Trim();
            Debug.Log("[Constellation] autoload " + folder);
            Game game = GamePersistence.LoadGame("persistent", folder, true, false);
            if (game == null || game.flightState == null)
            {
                Debug.LogError("[Constellation] autoload failed for " + folder);
                return;
            }
            HighLogic.SaveFolder = folder;
            HighLogic.CurrentGame = game;
            game.Start();
        }
    }

    [KSPAddon(KSPAddon.Startup.Flight, false)]
    public class Bridge : MonoBehaviour
    {
        private const int Port = 47821;
        private static UdpClient udp; // survives scene reloads
        private static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

        private void Start()
        {
            Application.runInBackground = true;
            if (udp == null)
            {
                udp = new UdpClient(new IPEndPoint(IPAddress.Loopback, Port));
                udp.Client.Blocking = false;
            }
            Debug.Log("[Constellation] bridge listening on " + Port);
        }

        private void Update()
        {
            for (int i = 0; i < 8 && udp != null && udp.Available > 0; i++)
            {
                IPEndPoint from = new IPEndPoint(IPAddress.Any, 0);
                byte[] data;
                try { data = udp.Receive(ref from); }
                catch (SocketException) { break; }
                string reply;
                try { reply = Handle(Encoding.UTF8.GetString(data).Trim().Split(' ')); }
                catch (Exception e) { reply = "{\"error\":" + Q(e.GetType().Name + ": " + e.Message) + "}"; }
                byte[] outb = Encoding.UTF8.GetBytes(reply);
                udp.Send(outb, outb.Length, from);
            }
        }

        private string Handle(string[] w)
        {
            string cmd = w.Length > 0 ? w[0] : "info";
            switch (cmd)
            {
                case "info": return Info();
                case "reshape": return Reshape(Body(w[1]), D(w[2]), D(w[3]));
                case "bodyorbit": return BodyOrbit(Body(w[1]), D(w[2]));
                case "map":
                    if (w.Length > 1 && w[1] == "off") MapView.ExitMapView(); else MapView.EnterMapView();
                    return "{\"ok\":true,\"map\":" + (MapView.MapIsEnabled ? "true" : "false") + "}";
                case "warp":
                    TimeWarp.SetRate(int.Parse(w[1], Inv), true, false);
                    return "{\"ok\":true,\"rate\":" + N(TimeWarp.CurrentRate) + "}";
                case "dismiss":
                    int closed = 0;
                    foreach (PopupDialog pd in FindObjectsOfType<PopupDialog>()) { pd.Dismiss(); closed++; }
                    PopupDialog.ClearPopUps();
                    return "{\"ok\":true,\"dismissed\":" + closed + "}";
                case "ui":
                    return Ui(w.Length > 1 ? w[1] : "find", w.Length > 2 ? w[2] : "");
                case "shot":
                    ScreenCapture.CaptureScreenshot(w[1]);
                    return "{\"ok\":true,\"file\":" + Q(w[1]) + "}";
                default: return "{\"error\":" + Q("unknown command " + cmd) + "}";
            }
        }

        // ---- commands ----------------------------------------------------------
        private string Info()
        {
            var sb = new StringBuilder("{");
            sb.Append("\"ut\":").Append(N(Planetarium.GetUniversalTime()));
            sb.Append(",\"warp\":").Append(N(TimeWarp.CurrentRate));
            sb.Append(",\"map\":").Append(MapView.MapIsEnabled ? "true" : "false");
            Vessel v = FlightGlobals.ActiveVessel;
            if (v != null) sb.Append(",\"vessel\":").Append(VesselJson(v));
            sb.Append(",\"bodies\":[");
            bool first = true;
            foreach (CelestialBody b in FlightGlobals.Bodies)
            {
                if (!first) sb.Append(',');
                first = false;
                sb.Append(BodyJson(b));
            }
            sb.Append("]}");
            return sb.ToString();
        }

        private string Reshape(CelestialBody b, double radiusScale, double gmScale)
        {
            double ut = Planetarium.GetUniversalTime();
            b.Radius *= radiusScale;
            b.gravParameter *= gmScale;
            b.Mass *= gmScale;
            b.gMagnitudeAtCenter = b.gravParameter;
            b.GeeASL = b.gravParameter / (b.Radius * b.Radius) / 9.80665;
            RecomputeSoi(b);
            if (b.scaledBody != null) b.scaledBody.transform.localScale *= (float)radiusScale;
            int touched = ReinitOrbitsAround(b, ut);
            return "{\"ok\":true,\"body\":" + BodyJson(b) + ",\"orbits_reinit\":" + touched + "}";
        }

        private string BodyOrbit(CelestialBody b, double smaScale)
        {
            if (b.orbit == null) throw new InvalidOperationException(b.bodyName + " has no orbit");
            double ut = Planetarium.GetUniversalTime();
            Orbit o = b.orbit;
            o.SetOrbit(o.inclination, o.eccentricity, o.semiMajorAxis * smaScale, o.LAN,
                o.argumentOfPeriapsis, o.meanAnomalyAtEpoch, o.epoch, o.referenceBody);
            o.Init();
            o.UpdateFromUT(ut);
            RecomputeSoi(b);
            int touched = ReinitOrbitsAround(b, ut);
            return "{\"ok\":true,\"body\":" + BodyJson(b) + ",\"orbits_reinit\":" + touched + "}";
        }

        // "ui find <substring>": active objects under any canvas whose name contains it.
        // "ui hide <substring>": deactivate the first such object that is a direct canvas child.
        private static string Ui(string mode, string pattern)
        {
            var names = new List<string>();
            foreach (Canvas c in FindObjectsOfType<Canvas>())
            {
                foreach (Transform t in c.transform)
                {
                    if (!t.gameObject.activeInHierarchy) continue;
                    if (pattern.Length > 0 && t.name.IndexOf(pattern, StringComparison.OrdinalIgnoreCase) < 0) continue;
                    if (mode == "hide")
                    {
                        t.gameObject.SetActive(false);
                        return "{\"ok\":true,\"hidden\":" + Q(c.name + "/" + t.name) + "}";
                    }
                    names.Add(c.name + "/" + t.name);
                }
            }
            var sb = new StringBuilder("{\"objects\":[");
            for (int i = 0; i < names.Count && i < 80; i++) { if (i > 0) sb.Append(','); sb.Append(Q(names[i])); }
            return sb.Append("]}").ToString();
        }

        // ---- helpers ---------------------------------------------------------------
        private static void RecomputeSoi(CelestialBody b)
        {
            if (b.orbit == null || b.referenceBody == null || b.referenceBody == b) return;
            double ratio = b.gravParameter / b.referenceBody.gravParameter;
            b.sphereOfInfluence = b.orbit.semiMajorAxis * Math.Pow(ratio, 0.4);
            b.hillSphere = b.orbit.semiMajorAxis * (1 - b.orbit.eccentricity) * Math.Pow(ratio / 3.0, 1.0 / 3.0);
        }

        private static int ReinitOrbitsAround(CelestialBody b, double ut)
        {
            int n = 0;
            foreach (Vessel v in FlightGlobals.Vessels)
            {
                if (v == null || v.orbit == null || v.orbit.referenceBody != b) continue;
                if (!v.packed) continue; // a physics-loaded vessel rewrites its own orbit each frame
                v.orbit.Init();
                v.orbit.UpdateFromUT(ut);
                if (v.patchedConicSolver != null) v.patchedConicSolver.Update();
                n++;
            }
            return n;
        }

        private static CelestialBody Body(string name)
        {
            CelestialBody b = FlightGlobals.Bodies.Find(x => string.Equals(x.bodyName, name, StringComparison.OrdinalIgnoreCase));
            if (b == null) throw new ArgumentException("no body " + name);
            return b;
        }

        private static string VesselJson(Vessel v)
        {
            Orbit o = v.orbit;
            var sb = new StringBuilder("{");
            sb.Append("\"name\":").Append(Q(v.vesselName));
            sb.Append(",\"body\":").Append(Q(o.referenceBody.bodyName));
            sb.Append(",\"packed\":").Append(v.packed ? "true" : "false");
            sb.Append(",\"situation\":").Append(Q(v.situation.ToString()));
            sb.Append(",\"sma\":").Append(N(o.semiMajorAxis));
            sb.Append(",\"ecc\":").Append(N(o.eccentricity));
            sb.Append(",\"inc\":").Append(N(o.inclination));
            sb.Append(",\"pe_alt\":").Append(N(o.PeA));
            sb.Append(",\"ap_alt\":").Append(N(o.ApA));
            sb.Append(",\"period\":").Append(N(o.period));
            sb.Append(",\"transition\":").Append(Q(o.patchEndTransition.ToString()));
            sb.Append(",\"next_body\":").Append(o.nextPatch != null && o.nextPatch.activePatch ? Q(o.nextPatch.referenceBody.bodyName) : "null");
            return sb.Append('}').ToString();
        }

        private static string BodyJson(CelestialBody b)
        {
            var sb = new StringBuilder("{");
            sb.Append("\"name\":").Append(Q(b.bodyName));
            sb.Append(",\"radius\":").Append(N(b.Radius));
            sb.Append(",\"gm\":").Append(N(b.gravParameter));
            sb.Append(",\"soi\":").Append(N(b.sphereOfInfluence));
            sb.Append(",\"sma\":").Append(b.orbit != null ? N(b.orbit.semiMajorAxis) : "null");
            sb.Append(",\"parent\":").Append(b.referenceBody != null && b.referenceBody != b ? Q(b.referenceBody.bodyName) : "null");
            return sb.Append('}').ToString();
        }

        private static double D(string s) { return double.Parse(s, Inv); }
        private static string N(double d) { return double.IsNaN(d) || double.IsInfinity(d) ? "null" : d.ToString("R", Inv); }

        private static string Q(string s)
        {
            return "\"" + (s ?? "").Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
        }
    }
}
