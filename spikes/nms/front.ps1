param([ValidateSet('pymhf', 'nms')] [string]$Which = 'pymhf')
# Bring the pyMHF GUI or the No Man's Sky window to the foreground.
Add-Type -Namespace CF -Name W -MemberDefinition @'
[DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc f, IntPtr l);
public delegate bool EnumProc(IntPtr h, IntPtr l);
[DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint p);
[DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, System.Text.StringBuilder s, int n);
[DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
[DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
[DllImport("user32.dll")] public static extern void keybd_event(byte k, byte s, uint f, UIntPtr e);
[DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
'@
$nms = (Get-Process NMS -ErrorAction Stop).Id
$title = if ($Which -eq 'pymhf') { 'pyMHF' } else { "No Man's Sky" }
$script:target = [IntPtr]::Zero
[CF.W]::EnumWindows({ param($w, $l)
    $p = 0; [void][CF.W]::GetWindowThreadProcessId($w, [ref]$p)
    if ($p -eq $nms -and [CF.W]::IsWindowVisible($w)) {
        $sb = New-Object System.Text.StringBuilder 256; [void][CF.W]::GetWindowText($w, $sb, 256)
        if ($sb.ToString() -eq $title) { $script:target = $w }
    }
    $true }, [IntPtr]::Zero) | Out-Null
[CF.W]::keybd_event(0x12, 0, 0, [UIntPtr]::Zero); [CF.W]::keybd_event(0x12, 0, 2, [UIntPtr]::Zero)
[void][CF.W]::SetForegroundWindow($script:target)
Start-Sleep -Milliseconds 300
"$Which in front: " + ([CF.W]::GetForegroundWindow() -eq $script:target)
