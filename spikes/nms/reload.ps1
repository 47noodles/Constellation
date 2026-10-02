# Click pyMHF's "Reload Mod" button for the first mod tab, then give focus back to NMS.
# The button sits at a fixed spot in the pyMHF window (client offset ~ +76,+86).
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
& "$here\front.ps1" pymhf | Out-Null
Add-Type -Namespace CR -Name M -MemberDefinition @'
[DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
[DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, UIntPtr e);
[DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
[DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
public struct RECT { public int L, T, R, B; }
'@
$r = New-Object CR.M+RECT
[void][CR.M]::GetWindowRect([CR.M]::GetForegroundWindow(), [ref]$r)
[void][CR.M]::SetCursorPos($r.L + 76, $r.T + 86)
Start-Sleep -Milliseconds 150
[CR.M]::mouse_event(2, 0, 0, 0, [UIntPtr]::Zero); [CR.M]::mouse_event(4, 0, 0, 0, [UIntPtr]::Zero)
Start-Sleep 3
& "$here\front.ps1" nms
