# Hold the machine awake for the overnight art run.
#
# Deliberately does NOT touch the power plan. This asserts wakefulness for
# as long as THIS PROCESS lives, via SetThreadExecutionState, and Windows
# drops the assertion automatically the moment the process exits — so a
# crash, a kill, or a reboot all restore the user's normal sleep behaviour
# with nothing left behind to clean up.
#
# ES_CONTINUOUS (0x80000000) | ES_SYSTEM_REQUIRED (0x00000001)
# Display is intentionally NOT held: the screen may sleep, the box may not.

Add-Type -Namespace Win32 -Name Power -MemberDefinition @'
[DllImport("kernel32.dll", SetLastError = true)]
public static extern uint SetThreadExecutionState(uint esFlags);
'@

$ES_CONTINUOUS      = [uint32]"0x80000000"
$ES_SYSTEM_REQUIRED = [uint32]"0x00000001"

$prev = [Win32.Power]::SetThreadExecutionState($ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED)
if ($prev -eq 0) {
    Write-Output "keepawake: FAILED to assert wakefulness"
    exit 1
}
Write-Output "keepawake: holding system awake (pid $PID); exit this process to release"

# The assertion is bound to this thread's lifetime, so we simply live.
while ($true) { Start-Sleep -Seconds 60 }
